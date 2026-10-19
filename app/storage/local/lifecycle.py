"""Start/stop database lokal: kolam koneksi dan migrasi otomatis saat aplikasi start (CV-3)."""

import asyncio
import logging

from fastapi import FastAPI

from app.core.config import Settings
from app.storage.local.db import buat_kolam, buka_kolam
from app.storage.local.migrasi import terapkan_migrasi

logger = logging.getLogger("app.storage.lifecycle")


def _siapkan(settings: Settings):
    """Buka kolam, jalankan migrasi, dan kembalikan kolam (blocking; dipanggil lewat thread)."""
    assert settings.local_database_url is not None
    dsn = settings.local_database_url.get_secret_value()
    kolam = buat_kolam(settings)
    try:
        buka_kolam(kolam, dsn)
        with kolam.connection() as conn:
            diterapkan = terapkan_migrasi(conn)
    except BaseException:
        kolam.close()
        raise
    logger.info("db_siap", extra={"migrasi_diterapkan": diterapkan})
    return kolam


async def mulai(app: FastAPI, settings: Settings) -> None:
    """Buka database lokal. Tanpa URL app tetap start (`db=None`); URL salah gagal cepat."""
    if settings.local_database_url is None:
        logger.warning("db_lokal_tidak_dikonfigurasi")
        app.state.db = None
        return
    app.state.db = await asyncio.to_thread(_siapkan, settings)


async def henti(app: FastAPI) -> None:
    """Tutup kolam koneksi bila ada (idempoten)."""
    kolam = getattr(app.state, "db", None)
    if kolam is not None:
        await asyncio.to_thread(kolam.close)
        app.state.db = None
