"""Repository `akun_lokal`: akun login lokal (hanya admin). Tanpa commit."""

from typing import Any

import psycopg
from psycopg.errors import UniqueViolation

from app.storage.local.db import kursor

USERNAME_MAKS = 100


class AkunSudahAda(RuntimeError):
    """Username sudah dipakai (tanpa membedakan huruf besar/kecil)."""


def _bersihkan(username: str) -> str:
    """Buang spasi tepi; kosong atau terlalu panjang -> ValueError."""
    bersih = username.strip()
    if not bersih or len(bersih) > USERNAME_MAKS:
        raise ValueError(f"username harus 1-{USERNAME_MAKS} karakter")
    return bersih


def buat(conn: psycopg.Connection, username: str, password_hash: str) -> int:
    """Buat akun admin lokal dan kembalikan id; username ganda -> AkunSudahAda."""
    bersih = _bersihkan(username)
    try:
        with conn.transaction(), kursor(conn) as cur:
            cur.execute(
                "INSERT INTO akun_lokal (username, password_hash) VALUES (%s, %s) RETURNING id",
                (bersih, password_hash),
            )
            baris = cur.fetchone()
    except UniqueViolation as exc:
        raise AkunSudahAda(f"username {bersih!r} sudah dipakai") from exc
    if baris is None:
        raise RuntimeError("INSERT akun_lokal tidak mengembalikan id")
    return int(baris["id"])


def ambil(conn: psycopg.Connection, username: str) -> dict[str, Any] | None:
    """Ambil akun by username (tidak peka huruf besar/kecil), atau None."""
    with kursor(conn) as cur:
        cur.execute(
            "SELECT * FROM akun_lokal WHERE lower(username) = lower(%s)", (username.strip(),)
        )
        return cur.fetchone()


def ganti_hash(conn: psycopg.Connection, username: str, hash_baru: str) -> bool:
    """Ganti hash password; True bila akun ada."""
    with kursor(conn) as cur:
        cur.execute(
            "UPDATE akun_lokal SET password_hash = %s, diubah_pada = now()"
            " WHERE lower(username) = lower(%s)",
            (hash_baru, username.strip()),
        )
        return cur.rowcount > 0


def set_aktif(conn: psycopg.Connection, username: str, aktif: bool) -> bool:
    """Aktifkan/nonaktifkan akun; True bila akun ada."""
    with kursor(conn) as cur:
        cur.execute(
            "UPDATE akun_lokal SET aktif = %s, diubah_pada = now()"
            " WHERE lower(username) = lower(%s)",
            (aktif, username.strip()),
        )
        return cur.rowcount > 0


def daftar(conn: psycopg.Connection) -> list[dict[str, Any]]:
    """Daftar akun tanpa kolom hash."""
    with kursor(conn) as cur:
        cur.execute(
            "SELECT id, username, peran, aktif, dibuat_pada, diubah_pada"
            " FROM akun_lokal ORDER BY id"
        )
        return cur.fetchall()
