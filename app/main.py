"""Titik masuk aplikasi FastAPI: pabrik `create_app`, lifespan, dan pemasangan route."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.ui.routes import UI_DIR
from app.ui.routes import router as ui_router

logger = logging.getLogger("app.main")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Bangun aplikasi FastAPI; `settings` kosong = ambil dari environment."""
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        """Pasang logging saat start dan catat start/stop aplikasi."""
        configure_logging(settings)
        logger.info("app_start", extra={"host": settings.host, "port": settings.port})
        try:
            yield
        finally:
            logger.info("app_stop")

    app = FastAPI(title="Verifikasi Casing", debug=settings.debug, lifespan=lifespan)
    app.state.settings = settings
    app.mount("/static", StaticFiles(directory=str(UI_DIR / "static")), name="static")
    app.include_router(ui_router)
    return app
