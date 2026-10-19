"""Start/stop database pabrik: nonaktif, tiruan, atau PostgreSQL (CV-4)."""

import asyncio
import logging

from fastapi import FastAPI

from app.core.config import Settings
from app.storage.factory.pemetaan import muat_pemetaan
from app.storage.factory.port import PabrikError
from app.storage.factory.postgres import PabrikPostgres
from app.storage.factory.tiruan import PabrikTiruan

logger = logging.getLogger("app.storage.factory.lifecycle")


class KonfigPabrikTidakLengkap(RuntimeError):
    """`factory_mode=postgres` tetapi URL atau berkas pemetaan belum diisi."""


def _siapkan(settings: Settings) -> PabrikPostgres:
    """Bangun adapter, validasi TLS, buka kolam tanpa menunggu (blocking; lewat thread)."""
    if settings.factory_database_url is None or settings.factory_mapping_file is None:
        raise KonfigPabrikTidakLengkap(
            "factory_mode=postgres butuh CASING_FACTORY_DATABASE_URL dan "
            "CASING_FACTORY_MAPPING_FILE."
        )
    pemetaan = muat_pemetaan(settings.factory_mapping_file)
    pabrik = PabrikPostgres(
        settings.factory_database_url.get_secret_value(),
        pemetaan,
        connect_timeout_s=settings.factory_connect_timeout_s,
        write_timeout_s=settings.factory_write_timeout_s,
    )
    pabrik.buka(tunggu=False)  # konfigurasi salah gagal cepat; jaringan mati tidak
    try:
        pabrik.ping()
    except PabrikError as exc:
        logger.error("pabrik_tidak_terjangkau", extra={"alasan": str(exc)})
    return pabrik


async def mulai(app: FastAPI, settings: Settings) -> None:
    """Pasang `app.state.pabrik` sesuai `factory_mode`; konfigurasi salah = gagal cepat."""
    mode = settings.factory_mode
    if mode == "nonaktif":
        app.state.pabrik = None
        logger.info("pabrik_nonaktif")
    elif mode == "tiruan":
        app.state.pabrik = PabrikTiruan()
        logger.warning("pabrik_mode_tiruan_hasil_tidak_dikirim")
    else:
        app.state.pabrik = await asyncio.to_thread(_siapkan, settings)
        logger.info("pabrik_siap")


async def henti(app: FastAPI) -> None:
    """Tutup adapter pabrik bila ada (idempoten)."""
    pabrik = getattr(app.state, "pabrik", None)
    if pabrik is not None:
        await asyncio.to_thread(pabrik.tutup)
        app.state.pabrik = None
