"""Pekerja retensi: hapus gambar lewat masa simpan, tandai rekaman, dan sapu gambar yatim (CV-13).

Urutan HAPUS FILE -> TANDAI BARIS: gagal di tengah tidak menghilangkan rekam jejak dan putaran
berikutnya idempoten. Hanya berkas `<cycle_id>.jpg` di dalam `image_dir` yang pernah dihapus.
"""

import logging
import re
import shutil
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from psycopg_pool import ConnectionPool

from app.domain.cycle_state import MesinSiklus
from app.storage.local import konfigurasi, retensi

logger = logging.getLogger("app.workers.retention")

POLA_CYCLE_ID = re.compile(r"[0-9a-zA-Z_-]{1,64}")
POLA_FOLDER_TANGGAL = re.compile(r"\d{4}-\d{2}-\d{2}")
BATCH = 200
BATCH_MAKS_PER_PUTARAN = 20
JEDA_AWAL_DETIK = 30.0
AMBANG_DISK_PENUH = 0.10


@dataclass
class HasilRetensi:
    """Hitungan satu putaran pembersihan."""

    dihapus: int = 0
    sudah_hilang: int = 0
    dilewati_tidak_aman: int = 0
    galat: int = 0
    byte_dibebaskan: int = 0
    yatim_dihapus: int = 0
    durasi_ms: int = 0
    batas: str = ""


def _jam_utc() -> datetime:
    """Waktu sekarang (aware, UTC)."""
    return datetime.now(UTC)


class PekerjaRetensi:
    """Thread berkala yang memanggil `jalankan_sekali` setiap `interval_s` detik."""

    def __init__(
        self,
        kolam: ConnectionPool,
        image_dir: Path,
        siklus: MesinSiklus | None,
        interval_s: float,
        jam: Callable[[], datetime] = _jam_utc,
        jeda_awal_s: float = JEDA_AWAL_DETIK,
    ) -> None:
        """`kolam` DB lokal; `image_dir` akar gambar; `siklus` untuk melindungi siklus berjalan."""
        self._kolam = kolam
        self._akar = Path(image_dir)
        self._siklus = siklus
        self._interval = interval_s
        self._jam = jam
        self._jeda_awal = jeda_awal_s
        self._henti = threading.Event()
        self._thread: threading.Thread | None = None
        self.terakhir: HasilRetensi | None = None

    def mulai(self) -> None:
        """Mulai thread latar (idempoten)."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._henti.clear()
        self._thread = threading.Thread(target=self._loop, name="retensi", daemon=True)
        self._thread.start()

    def henti(self) -> None:
        """Hentikan thread dan tunggu sebentar (idempoten)."""
        self._henti.set()
        t = self._thread
        if t is not None and t.is_alive():
            t.join(timeout=5)

    def _loop(self) -> None:
        """Putaran berkala; galat apa pun dicatat dan tidak mematikan thread."""
        if self._henti.wait(self._jeda_awal):
            return
        while not self._henti.is_set():
            try:
                self.jalankan_sekali()
            except Exception:
                logger.exception("retensi_putaran_galat")
            if self._henti.wait(self._interval):
                return

    def _cycle_berjalan(self) -> str | None:
        """cycle_id siklus yang sedang berjalan (tidak boleh disentuh), atau None."""
        return self._siklus.cycle_id if self._siklus is not None else None

    def _path_aman(self, path_teks: str, cycle_id: str) -> Path | None:
        """Path gambar bila di dalam `image_dir`, bernama `<cycle_id>.jpg`, dan bukan symlink."""
        try:
            p = Path(path_teks)
            if p.is_symlink() or p.name != f"{cycle_id}.jpg" or p.suffix != ".jpg":
                return None
            if not POLA_CYCLE_ID.fullmatch(cycle_id):
                return None
            if not p.resolve().is_relative_to(self._akar.resolve()):
                return None
        except (OSError, ValueError):
            return None
        return p

    def jalankan_sekali(self) -> HasilRetensi:
        """Satu putaran: fase A (berbasis DB) lalu fase B (sapuan yatim). Kembalikan hitungan."""
        mulai = time.perf_counter()
        hasil = HasilRetensi()
        try:
            with self._kolam.connection(timeout=5) as conn:
                _, konf = konfigurasi.ambil_terbaru(conn)
        except Exception:
            logger.warning("retensi_konfigurasi_tak_terbaca")
            return hasil
        batas = self._jam() - timedelta(days=konf.masa_simpan_gambar_hari)
        hasil.batas = batas.isoformat()
        self._fase_db(batas, hasil)
        self._fase_yatim(batas, hasil)
        hasil.durasi_ms = int((time.perf_counter() - mulai) * 1000)
        self.terakhir = hasil
        self._lapor(hasil)
        return hasil

    def _fase_db(self, batas: datetime, hasil: HasilRetensi) -> None:
        """Hapus file rekaman kedaluwarsa lalu tandai barisnya."""
        for _ in range(BATCH_MAKS_PER_PUTARAN):
            with self._kolam.connection(timeout=5) as conn:
                baris = retensi.kedaluwarsa(conn, batas, BATCH)
            if not baris:
                return
            ditandai: list[int] = []
            berjalan = self._cycle_berjalan()
            ada_tertunda = False
            for b in baris:
                if b["cycle_id"] == berjalan:
                    ada_tertunda = True
                    continue
                p = self._path_aman(b["path_gambar"], b["cycle_id"])
                if p is None:
                    hasil.dilewati_tidak_aman += 1
                    logger.error("retensi_path_tidak_aman", extra={"cycle_id": b["cycle_id"]})
                    ada_tertunda = True
                    continue
                try:
                    ukuran = p.stat().st_size
                    p.unlink()
                    hasil.dihapus += 1
                    hasil.byte_dibebaskan += ukuran
                except FileNotFoundError:
                    hasil.sudah_hilang += 1
                except OSError:
                    hasil.galat += 1
                    ada_tertunda = True
                    logger.error("retensi_hapus_gagal", extra={"cycle_id": b["cycle_id"]})
                    continue
                ditandai.append(b["id"])
            if ditandai:
                with self._kolam.connection(timeout=5) as conn, conn.transaction():
                    retensi.tandai_dibersihkan(conn, ditandai)
            if len(baris) < BATCH or (not ditandai and ada_tertunda):
                return

    def _fase_yatim(self, batas: datetime, hasil: HasilRetensi) -> None:
        """Hapus `<cycle_id>.jpg` lewat batas di folder tanggal yang tidak punya rekaman."""
        if not self._akar.is_dir():
            return
        tanggal_batas = batas.astimezone().date()
        berjalan = self._cycle_berjalan()
        for folder in sorted(self._akar.iterdir()):
            if (
                not folder.is_dir()
                or folder.is_symlink()
                or not POLA_FOLDER_TANGGAL.fullmatch(folder.name)
            ):
                continue
            try:
                if datetime.strptime(folder.name, "%Y-%m-%d").date() >= tanggal_batas:
                    continue
            except ValueError:
                continue
            kandidat: list[Path] = []
            for f in folder.iterdir():
                if f.is_symlink() or not f.is_file() or f.suffix != ".jpg":
                    continue
                if not POLA_CYCLE_ID.fullmatch(f.stem) or f.stem == berjalan:
                    continue
                try:
                    if f.stat().st_mtime >= batas.timestamp():
                        continue
                except OSError:
                    continue
                kandidat.append(f)
            if kandidat:
                try:
                    with self._kolam.connection(timeout=5) as conn:
                        punya = retensi.ada_rekaman(conn, [f.stem for f in kandidat])
                except Exception:
                    logger.warning("retensi_cek_yatim_gagal")
                    continue
                for f in kandidat:
                    if f.stem in punya:
                        continue
                    try:
                        hasil.byte_dibebaskan += f.stat().st_size
                        f.unlink()
                        hasil.yatim_dihapus += 1
                    except OSError:
                        hasil.galat += 1
            try:
                if not any(folder.iterdir()):
                    folder.rmdir()
            except OSError:
                pass

    def _lapor(self, hasil: HasilRetensi) -> None:
        """Log hasil putaran; peringatan disk hampir penuh; ERROR bila ada galat."""
        logger.info("retensi_selesai", extra=asdict(hasil))
        if hasil.galat:
            logger.error("retensi_ada_galat", extra={"galat": hasil.galat})
        try:
            pakai = shutil.disk_usage(self._akar if self._akar.exists() else self._akar.parent)
            if pakai.free / pakai.total < AMBANG_DISK_PENUH:
                logger.warning(
                    "disk_hampir_penuh",
                    extra={"bebas_persen": round(100 * pakai.free / pakai.total, 1)},
                )
        except OSError:
            pass
