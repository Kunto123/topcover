"""Start/stop inferensi: muat model aktif registri dan daftarkan gerbang mulai siklus (CV-8)."""

import asyncio
import logging

from fastapi import FastAPI

from app.core.config import Settings
from app.services.inference.mesin import MesinInferensi
from app.services.inference.pelari import PelariOpenVINO
from app.services.inference.registri import muat_model_aktif
from app.services.inference.tipe import ModelGagalDimuat

logger = logging.getLogger("app.inference.lifecycle")


def _buat_mesin(settings: Settings) -> MesinInferensi:
    """Bangun mesin dengan pelari OpenVINO sesuai `settings`."""
    return MesinInferensi(
        lambda: PelariOpenVINO(settings.inference_device, settings.inference_threads), settings
    )


def _muat(app: FastAPI, mesin: MesinInferensi) -> None:
    """Muat model aktif (blocking); kegagalan dicatat, aplikasi tetap hidup (siklus ditolak)."""
    kolam = getattr(app.state, "db", None)
    if kolam is None:
        pesan = "Database lokal tidak dikonfigurasi; model tidak bisa dimuat."
        mesin.catat_galat(pesan)
        logger.error("model_gagal_dimuat", extra={"alasan": pesan})
        return
    try:
        muat_model_aktif(kolam, mesin)
    except ModelGagalDimuat:
        pass  # sudah dicatat oleh mesin atau registri; status memuat alasan


async def mulai(app: FastAPI, settings: Settings) -> None:
    """Pasang `app.state.inferensi`; model dimuat di thread dan gerbang `model` didaftarkan."""
    mesin = _buat_mesin(settings)
    app.state.inferensi = mesin
    if not settings.inference_wajib:
        logger.warning("inferensi_tidak_wajib_gerbang_model_dimatikan")
    else:
        app.state.gerbang_mulai["model"] = lambda: (
            None if mesin.siap else f"Model belum siap: {mesin.galat or 'belum dimuat'}"
        )
    await asyncio.to_thread(_muat_aman, app, mesin)


def _muat_aman(app: FastAPI, mesin: MesinInferensi) -> None:
    """Bungkus `_muat` agar galat registri apa pun tidak menjatuhkan aplikasi."""
    try:
        _muat(app, mesin)
    except Exception as exc:  # galat tak terduga: tetap catat alasan di status
        mesin.catat_galat(f"Gagal memuat model ({type(exc).__name__}).")
        logger.exception("model_muat_galat_tak_terduga")


async def henti(app: FastAPI) -> None:
    """Hentikan mesin inferensi bila ada (idempoten)."""
    mesin = getattr(app.state, "inferensi", None)
    if mesin is not None:
        await asyncio.to_thread(mesin.henti)
        app.state.inferensi = None
