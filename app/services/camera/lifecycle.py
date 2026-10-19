"""Titik sambung start/stop layanan kamera (CV-7)."""

import asyncio
import logging

from fastapi import FastAPI

from app.core.config import Settings
from app.services.camera.pekerja import PekerjaKamera
from app.services.camera.sumber import KameraOpenCV

logger = logging.getLogger("app.camera.lifecycle")

KLIEN_PREVIEW_MAKS = 2


async def mulai(app: FastAPI, settings: Settings) -> None:
    """Luncurkan pekerja kamera bila `camera_enabled`; kamera hilang tidak menjatuhkan app."""
    app.state.mjpeg_sem = asyncio.Semaphore(KLIEN_PREVIEW_MAKS)
    if not settings.camera_enabled:
        app.state.kamera = None
        logger.info("kamera_dimatikan")
        return

    def pabrik() -> KameraOpenCV:
        """Bangun sumber kamera nyata; kontrol UVC dibiarkan kosong (menunggu Spike E)."""
        return KameraOpenCV(
            settings.camera_index,
            settings.camera_backend,
            settings.camera_width,
            settings.camera_height,
            settings.camera_fps,
        )

    pekerja = PekerjaKamera(pabrik, settings.image_dir, settings.jpeg_quality)
    app.state.kamera = pekerja
    pekerja.mulai()
    logger.info("kamera_pekerja_dimulai", extra={"index": settings.camera_index})


async def henti(app: FastAPI) -> None:
    """Hentikan pekerja kamera bila ada (idempoten)."""
    kamera = getattr(app.state, "kamera", None)
    if kamera is not None:
        await asyncio.to_thread(kamera.henti)
