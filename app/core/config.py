"""Konfigurasi aplikasi dari environment (`CASING_*`) dan file `.env`."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

HOST_LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})


class Settings(BaseSettings):
    """Pengaturan aplikasi; semua nilai bisa ditimpa lewat variabel `CASING_<NAMA>`."""

    model_config = SettingsConfigDict(env_prefix="CASING_", env_file=".env", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "INFO"
    log_dir: Path = Path("data/logs")
    debug: bool = False

    # CV-3 — database lokal. SecretStr agar DSN tidak bocor di repr/log.
    local_database_url: SecretStr | None = None

    # CV-7 — kamera dan gambar
    camera_enabled: bool = True
    camera_index: int = 0
    camera_backend: Literal["auto", "dshow", "msmf", "v4l2"] = "auto"
    camera_width: int = 1920
    camera_height: int = 1080
    camera_fps: int = 30
    preview_fps: int = 10
    preview_width: int = 960
    jpeg_quality: int = Field(92, ge=1, le=100)
    image_dir: Path = Path("data/images")

    # CV-11 — printer
    printer_mode: Literal["dryrun"] = "dryrun"

    # CV-6 — penangkap scanner (dikirim ke JS)
    scan_interval_ms: int = 50  # jeda maks antar karakter agar dianggap scanner
    scan_min_length: int = 3
    scan_idle_flush_ms: int = 150

    # CV-4 — database pabrik. Default `nonaktif`: tidak diam-diam mengirim ke mana pun.
    factory_mode: Literal["nonaktif", "tiruan", "postgres"] = "nonaktif"
    factory_database_url: SecretStr | None = None
    factory_mapping_file: Path | None = None
    factory_connect_timeout_s: float = Field(2.0, gt=0, le=10)
    factory_write_timeout_s: float = Field(3.0, gt=0, le=10)

    # CV-5 — auth
    auth_wajib: bool = True
    sesi_idle_menit: int = Field(30, ge=1)
    login_maks_gagal: int = Field(5, ge=1)
    login_kunci_menit: int = Field(15, ge=1)

    # CV-8 — inferensi
    inference_wajib: bool = True  # False = tanpa gerbang model (dev/test); siklus tetap jalan
    inference_device: str = "CPU"
    inference_threads: int | None = Field(None, ge=1)
    inference_ambang_deteksi: float = Field(0.25, ge=0, le=1)
    inference_ambang_mask: float = Field(0.5, gt=0, lt=1)
    inference_maks_deteksi: int = Field(20, ge=1, le=100)

    # CV-9 — model
    model_dir: Path = Path("data/models")
    model_upload_maks_mb: int = Field(500, ge=1)

    # CV-13 — pembersihan gambar
    retensi_aktif: bool = True
    retensi_interval_menit: int = Field(60, ge=1)

    # CV-12 — runner siklus
    siklus_timeout_inferensi_s: float = Field(6.0, gt=0)
    siklus_runner_aktif: bool = True  # False = tanpa runner (test/dev lama)

    @field_validator("host")
    @classmethod
    def _host_harus_loopback(cls, value: str) -> str:
        """Tolak alamat selain loopback: web UI hanya boleh didengarkan lokal."""
        if value not in HOST_LOOPBACK:
            diizinkan = ", ".join(sorted(HOST_LOOPBACK))
            raise ValueError(f"host harus loopback ({diizinkan}), dapat: {value!r}")
        return value

    @model_validator(mode="after")
    def _auth_nonaktif_hanya_debug(self) -> "Settings":
        """`auth_wajib=False` hanya untuk pengembangan: tolak bila `debug` mati."""
        if not self.auth_wajib and not self.debug:
            raise ValueError("auth_wajib=False hanya boleh bila debug=True")
        return self


@lru_cache
def get_settings() -> Settings:
    """Ambil Settings tunggal (di-cache); di test panggil `get_settings.cache_clear()`."""
    return Settings()


KETERANGAN: dict[str, str] = {
    "host": "Alamat dengar web UI; hanya loopback yang diizinkan.",
    "port": "Port web UI.",
    "log_level": "Level log (DEBUG/INFO/WARNING/ERROR).",
    "log_dir": "Folder berkas log JSON.",
    "debug": "Mode debug (halaman uji Spike C, traceback); jangan di produksi.",
    "local_database_url": "DSN PostgreSQL lokal; kosong = tanpa DB (siklus ditolak).",
    "camera_enabled": "Nyalakan layanan kamera.",
    "camera_index": "Indeks perangkat kamera.",
    "camera_backend": "Backend OpenCV kamera.",
    "camera_width": "Lebar capture yang diminta.",
    "camera_height": "Tinggi capture yang diminta.",
    "camera_fps": "FPS capture yang diminta.",
    "preview_fps": "FPS preview MJPEG.",
    "preview_width": "Lebar preview MJPEG (px).",
    "jpeg_quality": "Kualitas JPEG gambar tersimpan (1-100).",
    "image_dir": "Folder gambar capture (YYYY-MM-DD/<cycle_id>.jpg).",
    "printer_mode": "Mode printer (saat ini hanya dryrun).",
    "scan_interval_ms": "Jeda maks antar karakter agar dianggap pemindai.",
    "scan_min_length": "Panjang minimal kode hasil pindai.",
    "scan_idle_flush_ms": "Jeda diam untuk menutup satu pindaian.",
    "factory_mode": "nonaktif (default, siklus tidak bisa menyimpan), tiruan (uji), atau postgres.",
    "factory_database_url": "DSN database pabrik; host non-loopback wajib TLS terverifikasi.",
    "factory_mapping_file": "Berkas JSON pemetaan tabel/kolom pabrik.",
    "factory_connect_timeout_s": "Batas waktu koneksi ke pabrik (detik).",
    "factory_write_timeout_s": "Batas waktu tulis ke pabrik (detik).",
    "auth_wajib": "Login wajib; false hanya bersama debug (mode dev).",
    "sesi_idle_menit": "Sesi berakhir bila diam selama ini (menit).",
    "login_maks_gagal": "Jumlah gagal login sebelum akun dikunci.",
    "login_kunci_menit": "Lama kunci akun dan jendela hitung gagal (menit).",
    "inference_wajib": "Gerbang model aktif; false = siklus boleh tanpa model (dev/test).",
    "inference_device": "Perangkat OpenVINO (CPU).",
    "inference_threads": "Batas thread inferensi; kosong = otomatis.",
    "inference_ambang_deteksi": "Ambang skor minimum decoder (ragu tetap dilaporkan).",
    "inference_ambang_mask": "Ambang piksel mask.",
    "inference_maks_deteksi": "Maksimum deteksi per frame.",
    "model_dir": "Folder model hasil impor admin.",
    "model_upload_maks_mb": "Batas ukuran unggahan model (MB).",
    "retensi_aktif": "Nyalakan pembersihan gambar otomatis.",
    "retensi_interval_menit": "Jeda antar putaran pembersihan (menit).",
    "siklus_timeout_inferensi_s": "Batas waktu inferensi per siklus (detik).",
    "siklus_runner_aktif": "Pasang runner siklus; false = tanpa runner (test/dev).",
}
