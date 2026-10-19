"""Pekerja kamera: satu thread memegang kamera, menjaga frame terakhir, dan melayani capture.

Hanya thread pekerja yang menyentuh sumber frame. `ambil_gambar` menunggu frame yang lebih baru
(nomor urut `seq`) daripada saat dipanggil, sehingga yang disimpan adalah frame segar.
"""

import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

from app.core.logging import bind_cycle_id
from app.services.camera.penyimpanan import path_gambar, simpan_jpeg_atomik
from app.services.camera.sumber import KameraTidakTersedia, SumberFrame

logger = logging.getLogger("app.camera.pekerja")

__all__ = [
    "HasilCapture",
    "KameraTidakTersedia",
    "KameraTimeout",
    "PekerjaKamera",
    "StatusKamera",
]


class KameraTimeout(RuntimeError):
    """Tidak ada frame segar dalam batas waktu capture."""


@dataclass(frozen=True, slots=True)
class StatusKamera:
    """Status kamera untuk UI: koneksi, fps, resolusi, galat, umur frame, jumlah percobaan."""

    terhubung: bool
    fps: float
    resolusi: tuple[int, int] | None
    galat_terakhir: str | None
    frame_terakhir_umur_s: float | None
    percobaan_sambung: int


@dataclass(frozen=True, slots=True)
class HasilCapture:
    """Hasil capture: `path` JPEG, `frame` BGR yang dinilai, `waktu`, `seq`, `ukuran_byte`."""

    path: Path
    frame: np.ndarray
    waktu: datetime
    seq: int
    ukuran_byte: int


class PekerjaKamera:
    """Thread kamera: baca terus, simpan frame terakhir, reconnect dengan backoff."""

    def __init__(
        self,
        sumber_pabrik: Callable[[], SumberFrame],
        image_dir: Path,
        kualitas_jpeg: int,
        *,
        backoff_awal_s: float = 1.0,
        backoff_maks_s: float = 10.0,
        timeout_capture_s: float = 2.0,
        frame_buang: int = 1,
        gagal_baca_maks: int = 5,
    ) -> None:
        """`frame_buang` = jumlah frame segar yang dibuang setelah panggilan capture."""
        self._pabrik = sumber_pabrik
        self._image_dir = Path(image_dir)
        self._kualitas = kualitas_jpeg
        self._backoff_awal, self._backoff_maks = backoff_awal_s, backoff_maks_s
        self._timeout_capture = timeout_capture_s
        self._frame_buang = frame_buang
        self._gagal_baca_maks = gagal_baca_maks

        self._kond = threading.Condition()
        self._henti = threading.Event()
        self._thread: threading.Thread | None = None
        self._frame: np.ndarray | None = None
        self._seq = 0
        self._waktu_frame: float | None = None
        self._terhubung = False
        self._galat: str | None = None
        self._percobaan = 0
        self._resolusi: tuple[int, int] | None = None
        self._stempel: deque[float] = deque(maxlen=240)

    def mulai(self) -> None:
        """Luncurkan thread pekerja (tidak melempar walau kamera tidak ada)."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._henti.clear()
        self._thread = threading.Thread(target=self._jalankan, name="pekerja-kamera", daemon=True)
        self._thread.start()

    def henti(self, timeout: float = 3.0) -> None:
        """Hentikan pekerja (idempoten); peringatkan bila thread masih hidup setelah `timeout`."""
        self._henti.set()
        with self._kond:
            self._kond.notify_all()
        thread = self._thread
        if thread is not None:
            thread.join(timeout)
            if thread.is_alive():
                logger.warning("pekerja_kamera_belum_berhenti", extra={"timeout_s": timeout})

    def frame_terakhir(self) -> tuple[np.ndarray, int] | None:
        """Frame terakhir dan nomor urutnya; None bila belum ada atau kamera tidak terhubung."""
        with self._kond:
            if not self._terhubung or self._frame is None:
                return None
            return self._frame, self._seq

    def status(self) -> StatusKamera:
        """Ringkasan status kamera (fps dihitung dari jendela geser 1 detik)."""
        sekarang = time.monotonic()
        with self._kond:
            fps = float(sum(1 for t in self._stempel if sekarang - t <= 1.0))
            umur = None if self._waktu_frame is None else sekarang - self._waktu_frame
            return StatusKamera(
                self._terhubung, fps, self._resolusi, self._galat, umur, self._percobaan
            )

    def ambil_gambar(self, cycle_id: str) -> HasilCapture:
        """Ambil frame segar, simpan JPEG, kembalikan hasil (blocking; panggil via thread)."""
        mulai = time.perf_counter()
        with self._kond:
            if not self._terhubung:
                raise KameraTidakTersedia(self._galat or "Kamera belum terhubung")
            butuh = self._seq + 1 + self._frame_buang
            batas = time.monotonic() + self._timeout_capture
            while self._seq < butuh:
                if not self._terhubung:
                    raise KameraTidakTersedia(self._galat or "Kamera terputus saat capture")
                sisa = batas - time.monotonic()
                if sisa <= 0:
                    raise KameraTimeout(
                        f"Tidak ada frame segar dalam {self._timeout_capture:.1f} detik"
                    )
                self._kond.wait(sisa)
            frame, seq = self._frame, self._seq
        if frame is None:  # tidak mungkin terjadi setelah loop; menjaga tipe
            raise KameraTidakTersedia("Frame kosong")
        tunggu_ms = int((time.perf_counter() - mulai) * 1000)
        waktu = datetime.now().astimezone()
        path = path_gambar(self._image_dir, cycle_id, waktu)
        with bind_cycle_id(cycle_id):
            ukuran = simpan_jpeg_atomik(path, frame, self._kualitas)
            logger.info(
                "capture_selesai",
                extra={
                    "path": str(path),
                    "seq": seq,
                    "ukuran_byte": ukuran,
                    "tunggu_frame_ms": tunggu_ms,
                    "total_ms": int((time.perf_counter() - mulai) * 1000),
                },
            )
        return HasilCapture(path, frame, waktu, seq, ukuran)

    # ---- thread pekerja ----

    def _set_status(self, terhubung: bool, galat: str | None = None) -> None:
        """Perbarui status koneksi dan bangunkan penunggu capture."""
        with self._kond:
            self._terhubung = terhubung
            if galat is not None or terhubung:
                self._galat = galat
            self._kond.notify_all()

    def _jalankan(self) -> None:
        """Loop utama: buka -> baca terus -> bila putus, buka ulang dengan backoff."""
        backoff = self._backoff_awal
        while not self._henti.is_set():
            sumber = self._pabrik()
            with self._kond:
                self._percobaan += 1
            try:
                sumber.buka()
            except Exception as exc:
                pesan = str(exc) or type(exc).__name__
                logger.error("kamera_gagal_dibuka", extra={"galat": pesan})
                self._set_status(False, pesan)
                self._henti.wait(backoff)
                backoff = min(backoff * 2, self._backoff_maks)
                continue

            backoff = self._backoff_awal
            props = sumber.properti()
            with self._kond:
                self._resolusi = (int(props.get("lebar", 0)), int(props.get("tinggi", 0)))
            self._set_status(True, None)
            try:
                self._baca_terus(sumber)
            finally:
                try:
                    sumber.tutup()
                except Exception:
                    logger.exception("kamera_gagal_ditutup")
                self._set_status(False, self._galat)
            if not self._henti.is_set():
                self._henti.wait(self._backoff_awal)

    def _baca_terus(self, sumber: SumberFrame) -> None:
        """Baca frame sampai dihentikan atau gagal beruntun melewati batas."""
        gagal = 0
        while not self._henti.is_set():
            frame = sumber.baca()
            if frame is None:
                gagal += 1
                if gagal >= self._gagal_baca_maks:
                    pesan = f"Kamera terputus ({gagal} kegagalan baca beruntun)"
                    logger.error("kamera_terputus", extra={"galat": pesan})
                    with self._kond:
                        self._galat = pesan
                    return
                self._henti.wait(0.01)
                continue
            gagal = 0
            sekarang = time.monotonic()
            with self._kond:
                self._frame = frame
                self._seq += 1
                self._waktu_frame = sekarang
                self._stempel.append(sekarang)
                self._kond.notify_all()
