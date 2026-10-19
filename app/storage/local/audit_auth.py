"""Repository `audit_auth`: catatan login (lokal/pabrik). Hanya tabel; logika login ada di CV-5."""

from datetime import datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from app.storage.local.db import kursor

LIMIT_MAKS = 1000


def catat(
    conn: psycopg.Connection,
    *,
    username: str | None,
    sumber: str,
    hasil: str,
    peran: str | None = None,
    alasan: str | None = None,
    detail: dict[str, Any] | None = None,
) -> int:
    """Catat satu percobaan login dan kembalikan id. `sumber` lokal/pabrik; `hasil` sukses/gagal.

    Jangan menaruh password atau UID RFID mentah di `detail`.
    """
    with kursor(conn) as cur:
        cur.execute(
            "INSERT INTO audit_auth (username, sumber, peran, hasil, alasan, detail)"
            " VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (username, sumber, peran, hasil, alasan, Jsonb(detail or {})),
        )
        baris = cur.fetchone()
    if baris is None:
        raise RuntimeError("INSERT audit_auth tidak mengembalikan id")
    return int(baris["id"])


def daftar(
    conn: psycopg.Connection, *, username: str | None = None, limit: int = 100
) -> list[dict[str, Any]]:
    """Daftar audit terbaru dulu; `username` menyaring; `limit` 1..1000."""
    if not 1 <= limit <= LIMIT_MAKS:
        raise ValueError(f"limit harus 1..{LIMIT_MAKS}, dapat {limit}")
    sql = "SELECT * FROM audit_auth"
    params: list[Any] = []
    if username is not None:
        sql += " WHERE username = %s"
        params.append(username)
    sql += " ORDER BY waktu DESC, id DESC LIMIT %s"
    params.append(limit)
    with kursor(conn) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def gagal_beruntun(
    conn: psycopg.Connection, username: str, sejak: datetime
) -> tuple[int, datetime | None]:
    """Hitung gagal kredensial `username` sejak `sejak`: (jumlah, waktu gagal terakhir)."""
    # Mengabaikan percobaan `terkunci` dan `pabrik_tidak_tersedia`; sukses hasil CLI tidak mereset.
    if sejak.tzinfo is None:
        raise ValueError("sejak harus timezone-aware")
    with kursor(conn) as cur:
        cur.execute(
            "SELECT count(*) AS n, max(waktu) AS terakhir FROM audit_auth"
            " WHERE lower(username) = lower(%(u)s) AND hasil = 'gagal'"
            " AND coalesce(alasan, '') NOT IN ('terkunci', 'pabrik_tidak_tersedia')"
            " AND waktu >= %(sejak)s"
            " AND waktu > coalesce((SELECT max(waktu) FROM audit_auth"
            "   WHERE lower(username) = lower(%(u)s) AND hasil = 'sukses'"
            "   AND coalesce(alasan, '') NOT LIKE 'cli:%%'), '-infinity'::timestamptz)",
            {"u": username, "sejak": sejak},
        )
        baris = cur.fetchone()
    if baris is None:
        return 0, None
    return int(baris["n"]), baris["terakhir"]
