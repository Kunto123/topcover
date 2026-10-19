"""Repository `registri_model`: daftar, aktifkan (satu aktif), dan rollback. Tanpa commit."""

from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from app.storage.local.db import kursor
from app.storage.local.skema import MetadataModel

STATUS_SAH = frozenset({"aktif", "arsip", "nonaktif"})


class ModelTidakDitemukan(LookupError):
    """Id model yang diminta tidak ada di registri."""


class TidakAdaModelUntukRollback(RuntimeError):
    """Tidak ada model berstatus arsip (yang pernah aktif) untuk dikembalikan."""


def daftarkan(
    conn: psycopg.Connection,
    versi: str,
    path: str,
    metadata: MetadataModel,
    status: str = "nonaktif",
) -> int:
    """Daftarkan model baru dan kembalikan id; `status='aktif'` langsung mengaktifkannya."""
    if status not in STATUS_SAH:
        raise ValueError(f"status model tidak sah: {status!r}")
    with kursor(conn) as cur:
        cur.execute(
            "INSERT INTO registri_model (versi, path, status, metadata) VALUES (%s, %s, %s, %s)"
            " RETURNING id",
            (
                versi,
                path,
                "nonaktif" if status == "aktif" else status,
                Jsonb(metadata.model_dump()),
            ),
        )
        baris = cur.fetchone()
    if baris is None:
        raise RuntimeError("INSERT registri_model tidak mengembalikan id")
    model_id = int(baris["id"])
    if status == "aktif":
        aktifkan(conn, model_id)
    return model_id


def aktifkan(conn: psycopg.Connection, model_id: int) -> None:
    """Jadikan model `model_id` satu-satunya aktif; yang aktif sebelumnya menjadi arsip."""
    with conn.transaction(), kursor(conn) as cur:
        # Urutan penting: indeks unik parsial tidak ditunda, jadi arsipkan yang lama dulu.
        cur.execute(
            "UPDATE registri_model SET status = 'arsip' WHERE status = 'aktif' AND id <> %s",
            (model_id,),
        )
        cur.execute(
            "UPDATE registri_model SET status = 'aktif', diaktifkan_pada = now()"
            " WHERE id = %s RETURNING id",
            (model_id,),
        )
        if cur.fetchone() is None:
            raise ModelTidakDitemukan(f"model id={model_id} tidak ada di registri")


def rollback(conn: psycopg.Connection) -> int:
    """Aktifkan kembali model arsip yang terakhir aktif; kembalikan id-nya."""
    with conn.transaction(), kursor(conn) as cur:
        cur.execute(
            "SELECT id FROM registri_model WHERE status = 'arsip' AND diaktifkan_pada IS NOT NULL"
            " ORDER BY diaktifkan_pada DESC, id DESC LIMIT 1"
        )
        baris = cur.fetchone()
        if baris is None:
            raise TidakAdaModelUntukRollback("tidak ada model arsip untuk di-rollback")
        model_id = int(baris["id"])
    aktifkan(conn, model_id)
    return model_id


def aktif(conn: psycopg.Connection) -> dict[str, Any] | None:
    """Model yang sedang aktif, atau None."""
    with kursor(conn) as cur:
        cur.execute("SELECT * FROM registri_model WHERE status = 'aktif'")
        return cur.fetchone()


def daftar(conn: psycopg.Connection) -> list[dict[str, Any]]:
    """Semua model, yang terbaru dibuat dulu."""
    with kursor(conn) as cur:
        cur.execute("SELECT * FROM registri_model ORDER BY dibuat_pada DESC, id DESC")
        return cur.fetchall()
