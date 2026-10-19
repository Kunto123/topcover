"""Titik masuk aplikasi FastAPI: pabrik `create_app`, lifespan, dan pemasangan route."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.admin.deps import AlihkanKeLogin, handler_alihkan
from app.admin.routes import router_admin
from app.api.cycle import pasang as cycle_pasang
from app.api.cycle import router as cycle_router
from app.auth.lifecycle import pasang as auth_pasang
from app.auth.routes import router as auth_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.services.camera import lifecycle as camera_lifecycle
from app.services.camera.routes import router as camera_router
from app.services.cycle_runner import pasang as runner_pasang
from app.services.inference import lifecycle as inference_lifecycle
from app.services.inference.routes import router as inference_router
from app.storage.factory import lifecycle as factory_lifecycle
from app.storage.local import lifecycle as db_lifecycle
from app.ui.routes import UI_DIR
from app.ui.routes import router as ui_router
from app.workers import lifecycle as workers_lifecycle

logger = logging.getLogger("app.main")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Bangun aplikasi FastAPI; `settings` kosong = ambil dari environment."""
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Pasang logging, buka layanan (db, pabrik, inferensi, kamera, pekerja), tutup terbalik."""
        configure_logging(settings)
        logger.info("app_start", extra={"host": settings.host, "port": settings.port})
        try:
            await db_lifecycle.mulai(app, settings)
            await factory_lifecycle.mulai(app, settings)
            await inference_lifecycle.mulai(app, settings)
            await camera_lifecycle.mulai(app, settings)
            await workers_lifecycle.mulai(app, settings)
            yield
        finally:
            for nama, henti in (
                ("pekerja", workers_lifecycle.henti),
                ("kamera", camera_lifecycle.henti),
                ("inferensi", inference_lifecycle.henti),
                ("pabrik", factory_lifecycle.henti),
                ("db", db_lifecycle.henti),
            ):
                try:
                    await henti(app)
                except Exception:
                    logger.exception("henti_gagal", extra={"layanan": nama})
            logger.info("app_stop")

    app = FastAPI(title="Verifikasi Casing", debug=settings.debug, lifespan=lifespan)
    app.state.settings = settings
    app.mount("/static", StaticFiles(directory=str(UI_DIR / "static")), name="static")
    app.include_router(ui_router)
    app.include_router(camera_router)
    app.include_router(cycle_router)
    app.include_router(auth_router)
    app.include_router(inference_router)
    app.include_router(router_admin)
    app.add_exception_handler(AlihkanKeLogin, handler_alihkan)  # type: ignore[arg-type]
    cycle_pasang(app, settings)
    auth_pasang(app, settings)  # setelah cycle_pasang: CV-5 menimpa status_login/penangan_rfid
    runner_pasang(app, settings)  # setelah auth_pasang
    return app
