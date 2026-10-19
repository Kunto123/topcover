"""Impor model: unggah aman, ekstrak zip aman, konversi ke OpenVINO, validasi, dan registri (CV-9).

Model dari luar tidak tepercaya: zip dicek (zip-slip, bom, jumlah), nama disanitasi, dan model
divalidasi dengan benar-benar memuatnya sebelum didaftarkan. Berkas `.pt` adalah pickle PyTorch
(dapat mengeksekusi kode) — hanya dikonversi bila paket `ultralytics` ada dan sumbernya tepercaya.
"""

import logging
import re
import shutil
import threading
import time
import uuid
import zipfile
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psycopg
from psycopg_pool import ConnectionPool

from app.core.config import Settings
from app.core.states import CycleState
from app.domain.cycle_state import MesinSiklus
from app.services.inference.mesin import MesinInferensi, petakan_kelas
from app.services.inference.pelari import cari_xml
from app.services.inference.registri import muat_ulang_dari_registri
from app.services.inference.tipe import ModelGagalDimuat
from app.storage.local import audit_perubahan, registri_model
from app.storage.local.skema import MetadataModel

logger = logging.getLogger("app.model_import")

POLA_VERSI = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,49}$")
POLA_NAMA_BERKAS = re.compile(r"[^A-Za-z0-9._-]")
RASIO_KOMPRESI_MAKS = 100
ZIP_MAKS_BERKAS = 200
SIKLUS_IDLE = (CycleState.WAIT_DATAPART, CycleState.DONE)
JOB_DISIMPAN = 50


class ImporGagal(RuntimeError):
    """Impor gagal; pesan Indonesia aman ditampilkan ke admin (tanpa path server)."""


class UnggahTerlaluBesar(ImporGagal):
    """Berkas unggahan melebihi batas ukuran."""


class ZipTidakAman(ImporGagal):
    """Isi zip berbahaya atau melanggar batas (zip-slip, bom, terlalu banyak berkas)."""


class KonversiTidakTersedia(ImporGagal):
    """Konversi ke OpenVINO tidak bisa dilakukan di mesin ini (mis. paket opsional tidak ada)."""


class KelasTidakDiketahui(ImporGagal):
    """Nama kelas tidak ada di metadata dan tidak diisi manual."""


class ImporSibuk(ImporGagal):
    """Sudah ada impor yang berjalan."""


class SiklusSibuk(ImporGagal):
    """Operasi ditolak karena siklus pemeriksaan sedang berjalan."""


# ---------- berkas aman ----------


def sanitasi_nama(nama: str) -> str:
    """Ambil nama dasar berkas dan buang karakter di luar `[A-Za-z0-9._-]`; kosong -> galat."""
    dasar = re.split(r"[\\/]", nama or "")[-1]
    bersih = POLA_NAMA_BERKAS.sub("_", dasar).strip("._")[:100]
    if not bersih:
        raise ImporGagal("Nama berkas tidak valid.")
    return bersih


def validasi_versi(versi: str) -> str:
    """Versi 1-50 karakter `[A-Za-z0-9._-]` dan diawali alfanumerik; selain itu galat."""
    if not POLA_VERSI.fullmatch(versi or ""):
        raise ImporGagal("Versi harus 1-50 karakter huruf/angka/titik/garis, diawali huruf/angka.")
    return versi


async def simpan_aliran(aliran: AsyncIterator[bytes], tujuan: Path, batas_byte: int) -> int:
    """Tulis aliran ke `tujuan`; lewat `batas_byte` -> berkas dihapus dan UnggahTerlaluBesar."""
    total = 0
    tujuan.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(tujuan, "wb") as f:
            async for potong in aliran:
                total += len(potong)
                if total > batas_byte:
                    raise UnggahTerlaluBesar(
                        f"Berkas melebihi batas {batas_byte // (1024 * 1024)} MB."
                    )
                f.write(potong)
    except BaseException:
        tujuan.unlink(missing_ok=True)
        raise
    return total


def ekstrak_zip_aman(
    zip_path: Path, tujuan: Path, *, maks_berkas: int = ZIP_MAKS_BERKAS, maks_total_byte: int
) -> list[Path]:
    """Ekstrak zip dengan pemeriksaan zip-slip, symlink, enkripsi, bom, dan jumlah berkas."""
    tujuan.mkdir(parents=True, exist_ok=True)
    akar = tujuan.resolve()
    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as exc:
        raise ZipTidakAman("Berkas zip rusak.") from exc
    hasil: list[Path] = []
    with zf:
        info = [i for i in zf.infolist() if not i.is_dir()]
        if len(info) > maks_berkas:
            raise ZipTidakAman(f"Zip berisi terlalu banyak berkas (> {maks_berkas}).")
        if sum(i.file_size for i in info) > maks_total_byte:
            raise ZipTidakAman("Ukuran isi zip setelah diekstrak melebihi batas.")
        nama_kecil: set[str] = set()
        for i in info:
            if i.flag_bits & 0x1:
                raise ZipTidakAman("Zip terenkripsi tidak didukung.")
            if (i.external_attr >> 16) & 0o170000 == 0o120000:
                raise ZipTidakAman("Zip berisi symlink.")
            if i.compress_size and i.file_size / i.compress_size > RASIO_KOMPRESI_MAKS:
                raise ZipTidakAman("Rasio kompresi zip tidak wajar (bom zip).")
            if i.filename.lower() in nama_kecil:
                raise ZipTidakAman("Zip berisi nama berkas ganda.")
            nama_kecil.add(i.filename.lower())
            keluar = (akar / i.filename).resolve()
            if not keluar.is_relative_to(akar) or Path(i.filename).is_absolute():
                raise ZipTidakAman("Zip berisi path di luar folder tujuan.")
            keluar.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(i) as sumber, open(keluar, "wb") as f:
                shutil.copyfileobj(sumber, f)
            hasil.append(keluar)
    return hasil


# ---------- format, kelas, konversi ----------


def deteksi_format(path: Path) -> str:
    """Kenali `openvino`, `onnx`, `pt`, atau `zip` dari isi/ekstensi; tak dikenal -> ImporGagal."""
    if path.is_dir():
        if list(path.glob("*.xml")):
            return "openvino"
        raise ImporGagal("Folder tidak berisi model OpenVINO (.xml).")
    with open(path, "rb") as f:
        kepala = f.read(4)
    if kepala[:2] == b"PK":
        return "zip"
    ext = path.suffix.lower()
    if ext == ".xml":
        return "openvino"
    if ext == ".onnx":
        return "onnx"
    if ext == ".pt":
        return "pt"
    raise ImporGagal("Format tidak dikenal; gunakan zip, .onnx, .pt, atau OpenVINO (.xml).")


def baca_nama_kelas(folder: Path, kelas_manual: list[str] | None) -> list[str]:
    """Baca nama kelas dari `metadata.yaml` (format Ultralytics) atau pakai input manual."""
    meta = folder / "metadata.yaml"
    if meta.is_file():
        nama = _urai_names(meta.read_text(encoding="utf-8", errors="replace"))
        if nama:
            return nama
    if kelas_manual:
        return list(kelas_manual)
    raise KelasTidakDiketahui(
        "Nama kelas tidak ditemukan di model; isi kolom 'kelas' (urutan sesuai indeks kelas)."
    )


def _urai_names(teks: str) -> list[str]:
    """Urai blok `names:` YAML sederhana (peta `0: kiri`, peta inline, atau daftar)."""
    baris = teks.splitlines()
    for n, b in enumerate(baris):
        if b.strip().startswith("names:"):
            sisa = b.split(":", 1)[1].strip()
            if sisa.startswith("{") or sisa.startswith("["):
                isi = sisa.strip("{}[]")
                butir = [x.strip() for x in isi.split(",") if x.strip()]
                return [x.split(":", 1)[-1].strip().strip("'\"") for x in butir]
            hasil: dict[int, str] = {}
            urut: list[str] = []
            for lanjut in baris[n + 1 :]:
                if not lanjut.strip() or not lanjut.startswith((" ", chr(9), "- ")):
                    break
                s = lanjut.strip()
                if s.startswith("- "):
                    urut.append(s[2:].strip().strip("'\""))
                elif ":" in s:
                    k, v = s.split(":", 1)
                    if k.strip().isdigit():
                        hasil[int(k)] = v.strip().strip("'\"")
            if urut:
                return urut
            return [hasil[k] for k in sorted(hasil)]
    return []


def konversi_onnx(onnx: Path, keluar: Path, imgsz: int) -> Path:
    """Konversi ONNX ke OpenVINO IR statis `(1,3,imgsz,imgsz)`; kembalikan folder keluaran."""
    try:
        import openvino as ov
    except ImportError as exc:  # pragma: no cover
        raise KonversiTidakTersedia("Paket openvino tidak terpasang.") from exc
    keluar.mkdir(parents=True, exist_ok=True)
    try:
        model = ov.convert_model(str(onnx))
        if model.input(0).get_partial_shape().is_dynamic:
            model.reshape([1, 3, imgsz, imgsz])
        ov.save_model(model, str(keluar / "model.xml"))
    except Exception as exc:
        raise ImporGagal(f"Konversi ONNX gagal: {str(exc)[:300]}") from exc
    return keluar


def konversi_pt(pt: Path, keluar: Path, imgsz: int) -> Path:
    """Konversi `.pt` lewat Ultralytics (opsional); tanpa paketnya -> KonversiTidakTersedia."""
    try:
        from ultralytics import YOLO  # type: ignore[import-not-found]
    except ImportError as exc:
        raise KonversiTidakTersedia(
            "Konversi .pt butuh paket ultralytics (pip install .[konversi]); atau ekspor ke "
            "ONNX/OpenVINO di PC training lalu unggah hasilnya."
        ) from exc
    try:
        hasil = Path(YOLO(str(pt)).export(format="openvino", imgsz=imgsz, dynamic=False))
    except Exception as exc:
        raise ImporGagal(f"Konversi .pt gagal: {str(exc)[:300]}") from exc
    keluar.mkdir(parents=True, exist_ok=True)
    folder = hasil if hasil.is_dir() else hasil.parent
    for isi in folder.iterdir():
        if isi.is_file():
            shutil.copy2(isi, keluar / isi.name)
    return keluar


# ---------- job ----------


@dataclass
class Job:
    """Status satu impor: `status` (antri..selesai|gagal), `pesan`, dan `model_id` bila selesai."""

    id: str
    versi: str
    status: str = "antri"
    pesan: str = ""
    model_id: int | None = None
    mulai: float = field(default_factory=time.time)
    selesai: float | None = None

    def ringkas(self) -> dict[str, Any]:
        """Bentuk JSON untuk API."""
        return {
            "id": self.id,
            "versi": self.versi,
            "status": self.status,
            "pesan": self.pesan,
            "model_id": self.model_id,
        }


class PekerjaImpor:
    """Menjalankan impor satu per satu di thread latar dan menyimpan status job."""

    def __init__(
        self,
        kolam: ConnectionPool,
        mesin: MesinInferensi,
        siklus: MesinSiklus,
        settings: Settings,
    ) -> None:
        """`kolam` registri, `mesin` untuk validasi, `siklus` untuk cek idle, `settings` jalur."""
        self._kolam, self._mesin, self._siklus, self._s = kolam, mesin, siklus, settings
        self._lock = threading.Lock()
        self._job: dict[str, Job] = {}
        self._berjalan = False

    @property
    def staging_dir(self) -> Path:
        """Folder sementara unggahan/ekstrak/konversi."""
        return Path(self._s.model_dir) / ".staging"

    def status(self, job_id: str) -> Job | None:
        """Job berdasarkan id, atau None."""
        with self._lock:
            return self._job.get(job_id)

    def ajukan(
        self,
        berkas: Path,
        versi: str,
        *,
        kelas_manual: list[str] | None,
        imgsz: int,
        aktifkan: bool,
        oleh: str,
    ) -> Job:
        """Daftarkan job dan mulai thread; impor lain berjalan / siklus sibuk -> galat."""
        versi = validasi_versi(versi)
        if self._siklus.state not in SIKLUS_IDLE:
            raise SiklusSibuk("Siklus pemeriksaan sedang berjalan; coba lagi setelah selesai.")
        with self._lock:
            if self._berjalan:
                raise ImporSibuk("Masih ada impor yang berjalan.")
            self._berjalan = True
            job = Job(uuid.uuid4().hex[:12], versi)
            self._job[job.id] = job
            for lama in sorted(self._job.values(), key=lambda j: j.mulai)[:-JOB_DISIMPAN]:
                self._job.pop(lama.id, None)
        threading.Thread(
            target=self._jalankan,
            args=(job, berkas, kelas_manual, imgsz, aktifkan, oleh),
            name="impor-model",
            daemon=True,
        ).start()
        return job

    def _ubah(self, job: Job, status: str, pesan: str = "") -> None:
        """Perbarui status job dan catat ke log."""
        job.status, job.pesan = status, pesan
        logger.info("impor_tahap", extra={"job": job.id, "status": status, "versi": job.versi})

    def _jalankan(
        self,
        job: Job,
        berkas: Path,
        kelas_manual: list[str] | None,
        imgsz: int,
        aktifkan: bool,
        oleh: str,
    ) -> None:
        """Pipa impor penuh; gagal di titik mana pun membersihkan staging dan folder tujuan."""
        kerja = self.staging_dir / job.id
        tujuan = Path(self._s.model_dir) / job.versi
        tujuan_dibuat = False
        try:
            folder = self._siapkan_folder(job, berkas, kerja, imgsz)
            self._ubah(job, "validasi")
            kelas = baca_nama_kelas(folder, kelas_manual)
            petakan_kelas(kelas)
            info = self._mesin.periksa(folder, kelas)
            self._ubah(job, "simpan")
            if tujuan.exists():
                raise ImporGagal(f"Folder versi {job.versi!r} sudah ada.")
            tujuan.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(folder, tujuan)
            tujuan_dibuat = True
            meta = MetadataModel(
                nama_kelas=kelas,
                format_asal=deteksi_format(berkas) if berkas.exists() else "tidak diketahui",
                ukuran_input=info.ukuran_input,
            )
            with self._kolam.connection() as conn, conn.transaction():
                xml = cari_xml(tujuan)
                job.model_id = registri_model.daftarkan(conn, job.versi, str(xml), meta)
                audit_perubahan.catat(
                    conn,
                    oleh=oleh,
                    aksi="model.daftarkan",
                    objek=f"model:{job.versi}",
                    detail={
                        "id": job.model_id,
                        "kelas": kelas,
                        "ukuran_input": list(info.ukuran_input),
                    },
                )
            if aktifkan:
                self._ubah(job, "aktifkan")
                aktifkan_model(self._kolam, self._mesin, self._siklus, job.model_id, oleh)
            self._ubah(job, "selesai", f"Model {job.versi} terdaftar.")
        except (ImporGagal, ModelGagalDimuat, psycopg.Error, OSError) as exc:
            pesan = (
                str(exc)
                if isinstance(exc, ImporGagal | ModelGagalDimuat)
                else (f"Gagal ({type(exc).__name__}).")
            )
            if tujuan_dibuat and job.model_id is None:
                shutil.rmtree(tujuan, ignore_errors=True)
            self._ubah(job, "gagal", pesan[:500])
            self._catat_gagal(job, oleh, pesan)
        except Exception as exc:
            logger.exception("impor_galat_tak_terduga", extra={"job": job.id})
            if tujuan_dibuat and job.model_id is None:
                shutil.rmtree(tujuan, ignore_errors=True)
            self._ubah(job, "gagal", f"Galat internal ({type(exc).__name__}).")
            self._catat_gagal(job, oleh, type(exc).__name__)
        finally:
            shutil.rmtree(kerja, ignore_errors=True)
            induk = berkas.parent
            if induk.resolve() != self.staging_dir.resolve() and induk.resolve().is_relative_to(
                self.staging_dir.resolve()
            ):
                shutil.rmtree(induk, ignore_errors=True)
            job.selesai = time.time()
            with self._lock:
                self._berjalan = False

    def _siapkan_folder(self, job: Job, berkas: Path, kerja: Path, imgsz: int) -> Path:
        """Ekstrak/konversi sesuai format dan kembalikan folder OpenVINO siap divalidasi."""
        fmt = deteksi_format(berkas)
        if fmt == "zip":
            self._ubah(job, "ekstrak")
            isi = kerja / "isi"
            ekstrak_zip_aman(
                berkas, isi, maks_total_byte=self._s.model_upload_maks_mb * 4 * 1024 * 1024
            )
            xml = sorted(isi.rglob("*.xml"))
            onnx = sorted(isi.rglob("*.onnx"))
            pt = sorted(isi.rglob("*.pt"))
            kandidat = [("openvino", xml), ("onnx", onnx), ("pt", pt)]
            ada = [(f, k) for f, k in kandidat if k]
            if len(ada) != 1 or len(ada[0][1]) != 1:
                raise ImporGagal("Zip harus berisi tepat satu model (.xml, .onnx, atau .pt).")
            fmt, berkas = ada[0][0], ada[0][1][0]
        if fmt == "openvino":
            return berkas.parent if berkas.is_file() else berkas
        self._ubah(job, "konversi")
        keluar = kerja / "ov"
        if fmt == "onnx":
            return konversi_onnx(berkas, keluar, imgsz)
        return konversi_pt(berkas, keluar, imgsz)

    def _catat_gagal(self, job: Job, oleh: str, pesan: str) -> None:
        """Catat kegagalan impor ke audit (tanpa isi berkas); galat audit hanya dilog."""
        try:
            with self._kolam.connection() as conn:
                audit_perubahan.catat(
                    conn,
                    oleh=oleh,
                    aksi="model.impor_gagal",
                    objek=f"model:{job.versi}",
                    detail={"alasan": pesan[:300]},
                )
        except Exception:
            logger.warning("audit_impor_gagal_tidak_tercatat")


# ---------- aktivasi & rollback ----------


def _pastikan_idle(siklus: MesinSiklus) -> None:
    """Tolak operasi bila siklus sedang berjalan."""
    if siklus.state not in SIKLUS_IDLE:
        raise SiklusSibuk("Siklus pemeriksaan sedang berjalan; coba lagi setelah selesai.")


def _aktifkan_dan_muat(
    kolam: ConnectionPool,
    mesin: MesinInferensi,
    model_id: int,
    oleh: str,
    aksi: str,
    cari_target: Any,
) -> str:
    """Ubah registri + audit lalu muat ulang; gagal muat -> kembalikan registri dan lempar."""
    with kolam.connection() as conn, conn.transaction():
        sebelum = registri_model.aktif(conn)
        target_id = cari_target(conn) if model_id < 0 else model_id
        status_target = next(
            (m["status"] for m in registri_model.daftar(conn) if m["id"] == target_id), None
        )
        registri_model.aktifkan(conn, target_id)
        audit_perubahan.catat(
            conn,
            oleh=oleh,
            aksi=aksi,
            objek=f"model:{target_id}",
            detail={"sebelum_id": sebelum["id"] if sebelum else None},
        )
    try:
        return muat_ulang_dari_registri(kolam, mesin)
    except ModelGagalDimuat as exc:
        with kolam.connection() as conn, conn.transaction():
            if sebelum is not None:
                registri_model.aktifkan(conn, sebelum["id"])
            conn.execute(
                "UPDATE registri_model SET status = %s, diaktifkan_pada = NULL WHERE id = %s"
                " AND status <> 'aktif'",
                (status_target or "nonaktif", target_id),
            )
            audit_perubahan.catat(
                conn,
                oleh=oleh,
                aksi="model.aktifkan_gagal",
                objek=f"model:{target_id}",
                detail={"alasan": str(exc)[:300]},
            )
        raise


def _id_rollback(conn: psycopg.Connection) -> int:
    """Id model arsip yang terakhir aktif; tidak ada -> TidakAdaModelUntukRollback."""
    baris = conn.execute(
        "SELECT id FROM registri_model WHERE status = 'arsip' AND diaktifkan_pada IS NOT NULL"
        " ORDER BY diaktifkan_pada DESC, id DESC LIMIT 1"
    ).fetchone()
    if baris is None:
        raise registri_model.TidakAdaModelUntukRollback("tidak ada model arsip untuk di-rollback")
    return int(baris["id"])


def aktifkan_model(
    kolam: ConnectionPool, mesin: MesinInferensi, siklus: MesinSiklus, model_id: int, oleh: str
) -> str:
    """Aktifkan model `model_id` tanpa restart; hanya saat siklus idle. Kembalikan versinya."""
    _pastikan_idle(siklus)
    return _aktifkan_dan_muat(kolam, mesin, model_id, oleh, "model.aktifkan", None)


def rollback_model(
    kolam: ConnectionPool, mesin: MesinInferensi, siklus: MesinSiklus, oleh: str
) -> str:
    """Kembalikan model arsip yang terakhir aktif tanpa restart; hanya saat siklus idle."""
    _pastikan_idle(siklus)
    return _aktifkan_dan_muat(kolam, mesin, -1, oleh, "model.rollback", _id_rollback)


__all__ = [
    "ImporGagal",
    "ImporSibuk",
    "KelasTidakDiketahui",
    "KonversiTidakTersedia",
    "PekerjaImpor",
    "SiklusSibuk",
    "UnggahTerlaluBesar",
    "ZipTidakAman",
    "aktifkan_model",
    "baca_nama_kelas",
    "deteksi_format",
    "ekstrak_zip_aman",
    "rollback_model",
    "sanitasi_nama",
    "simpan_aliran",
    "validasi_versi",
]
