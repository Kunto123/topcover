"""Start/stop pekerja latar: retensi gambar (CV-13). Dimulai setelah kamera, ditutup lebih dulu."""

import asyncio
import logging

from fastapi import FastAPI

from app.core.config import Settings
from app.workers.retention import PekerjaRetensi

logger = logging.getLogger("app.workers.lifecycle")


async def mulai(app: FastAPI, settings: Settings) -> None:
    """Siapkan daftar pekerja dan jalankan retensi bila aktif dan DB tersedia."""
    app.state.pekerja = []
    app.state.retensi = None
    if not settings.retensi_aktif:
        logger.info("retensi_dimatikan")
        return
    kolam = getattr(app.state, "db", None)
    if kolam is None:
        logger.info("retensi_dilewati_tanpa_db")
        return
    pekerja = PekerjaRetensi(
        kolam,
        settings.image_dir,
        getattr(app.state, "siklus", None),
        settings.retensi_interval_menit * 60,
    )
    pekerja.mulai()
    app.state.pekerja.append(pekerja)
    app.state.retensi = pekerja
    logger.info("retensi_dimulai", extra={"interval_menit": settings.retensi_interval_menit})


async def henti(app: FastAPI) -> None:
    """Hentikan semua pekerja; galat satu pekerja tidak menghalangi yang lain (idempoten)."""
    pekerja = getattr(app.state, "pekerja", [])
    for p in list(pekerja):
        try:
            await asyncio.to_thread(p.henti)
        except Exception:
            logger.exception("pekerja_henti_gagal")
    app.state.pekerja = []
    app.state.retensi = None
