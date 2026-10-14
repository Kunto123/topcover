"""Konfigurasi aplikasi dari environment (`CASING_*`) dan file `.env`."""

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
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

    @field_validator("host")
    @classmethod
    def _host_harus_loopback(cls, value: str) -> str:
        """Tolak alamat selain loopback: web UI hanya boleh didengarkan lokal."""
        if value not in HOST_LOOPBACK:
            diizinkan = ", ".join(sorted(HOST_LOOPBACK))
            raise ValueError(f"host harus loopback ({diizinkan}), dapat: {value!r}")
        return value


@lru_cache
def get_settings() -> Settings:
    """Ambil Settings tunggal (di-cache); di test panggil `get_settings.cache_clear()`."""
    return Settings()
