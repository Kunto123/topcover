"""Repository `audit_perubahan`: jejak perubahan varian, konfigurasi, dan model. Tanpa commit."""

from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from app.storage.local.db import kursor

LIMIT_MAKS = 1000


def catat(
    conn: psycopg.Connection,
    *,
    oleh: str,
    aksi: str,
    objek: str,
    detail: dict[str, Any] | None = None,
    versi_sebelum: int | None = None,
    versi_sesudah: int | None = None,
) -> int:
    """Catat satu perubahan dan kembalikan id. Jangan menaruh password/token di `detail`."""
    if not oleh.strip() or not aksi.strip() or not objek.strip():
        raise ValueError("oleh, aksi, dan objek tidak boleh kosong")
    with kursor(conn) as cur:
        cur.execute(
            "INSERT INTO audit_perubahan (oleh, aksi, objek, detail, versi_sebelum, versi_sesudah)"
            " VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (oleh, aksi, objek, Jsonb(detail or {}), versi_sebelum, versi_sesudah),
        )
        baris = cur.fetchone()
    if baris is None:
        raise RuntimeError("INSERT audit_perubahan tidak mengembalikan id")
    return int(baris["id"])


def daftar(
    conn: psycopg.Connection, *, objek: str | None = None, limit: int = 100
) -> list[dict[str, Any]]:
    """Daftar perubahan terbaru dulu; `objek` menyaring; `limit` 1..1000."""
    if not 1 <= limit <= LIMIT_MAKS:
        raise ValueError(f"limit harus 1..{LIMIT_MAKS}, dapat {limit}")
    sql = "SELECT * FROM audit_perubahan"
    params: list[Any] = []
    if objek is not None:
        sql += " WHERE objek = %s"
        params.append(objek)
    sql += " ORDER BY waktu DESC, id DESC LIMIT %s"
    params.append(limit)
    with kursor(conn) as cur:
        cur.execute(sql, params)
        return cur.fetchall()
