"""Muat model aktif dari registri (PostgreSQL lokal) ke `MesinInferensi`."""

import logging
from pathlib import Path

import psycopg
from psycopg_pool import ConnectionPool
from pydantic import ValidationError

from app.services.inference.mesin import MesinInferensi
from app.services.inference.tipe import ModelGagalDimuat
from app.storage.local import registri_model
from app.storage.local.skema import MetadataModel

logger = logging.getLogger("app.inference.registri")


def _model_aktif(kolam: ConnectionPool) -> tuple[Path, str, list[str]]:
    """Baca model aktif dari registri; kembalikan (path, versi, nama_kelas) tervalidasi."""
    try:
        with kolam.connection(timeout=5) as conn:
            baris = registri_model.aktif(conn)
    except psycopg.Error as exc:
        raise ModelGagalDimuat(f"Registri model tidak terbaca ({type(exc).__name__}).") from exc
    if baris is None:
        raise ModelGagalDimuat("Belum ada model aktif di registri.")
    try:
        meta = MetadataModel.model_validate(baris["metadata"])
    except ValidationError as exc:
        raise ModelGagalDimuat(
            f"Metadata model id={baris['id']} ({baris['versi']}) tidak valid: "
            f"{exc.error_count()} galat."
        ) from exc
    path = Path(baris["path"])
    if not path.exists():
        raise ModelGagalDimuat(f"Berkas model {baris['versi']} tidak ditemukan: {path}")
    return path, str(baris["versi"]), meta.nama_kelas


def _model_aktif_atau_catat(
    kolam: ConnectionPool, mesin: MesinInferensi
) -> tuple[Path, str, list[str]]:
    """Seperti `_model_aktif`, tetapi alasan gagal disimpan di `mesin` agar tampil di status."""
    try:
        return _model_aktif(kolam)
    except ModelGagalDimuat as exc:
        mesin.catat_galat(str(exc))
        logger.error("model_gagal_dimuat", extra={"alasan": str(exc)})
        raise


def muat_model_aktif(kolam: ConnectionPool, mesin: MesinInferensi) -> str:
    """Muat model aktif registri ke `mesin`; kembalikan versinya. Gagal -> ModelGagalDimuat."""
    path, versi, kelas = _model_aktif_atau_catat(kolam, mesin)
    mesin.muat(path, versi, kelas)
    return versi


def muat_ulang_dari_registri(kolam: ConnectionPool, mesin: MesinInferensi) -> str:
    """Ganti model di `mesin` dengan model aktif registri (model lama aman bila gagal)."""
    path, versi, kelas = _model_aktif_atau_catat(kolam, mesin)
    mesin.muat_ulang(path, versi, kelas)
    return versi
