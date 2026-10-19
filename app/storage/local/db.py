"""Koneksi PostgreSQL lokal: kolam koneksi, koneksi tunggal, dan helper transaksi.

DSN dan password TIDAK boleh muncul di log atau pesan galat; hanya `host:port/dbname`.
"""

from contextlib import AbstractContextManager

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import DictRow, dict_row
from psycopg_pool import ConnectionPool, PoolTimeout

from app.core.config import Settings

WAKTU_KONEK_DETIK = 5


class DatabaseTidakTersedia(RuntimeError):
    """Database lokal tidak terjangkau; pesan hanya memuat host:port/dbname (tanpa kredensial)."""


def ringkas_target(dsn: str) -> str:
    """Ringkas DSN menjadi `host:port/dbname` yang aman untuk pesan dan log."""
    info = conninfo_to_dict(dsn)
    return f"{info.get('host', 'localhost')}:{info.get('port', '5432')}/{info.get('dbname', '?')}"


def buat_kolam(settings: Settings) -> "ConnectionPool[psycopg.Connection[DictRow]]":
    """Buat kolam (belum dibuka) dari `settings.local_database_url`; kosong -> ValueError."""
    if settings.local_database_url is None:
        raise ValueError("local_database_url belum diisi")
    dsn = settings.local_database_url.get_secret_value()
    return ConnectionPool(
        conninfo=dsn,
        min_size=1,
        max_size=4,
        kwargs={"row_factory": dict_row, "connect_timeout": WAKTU_KONEK_DETIK},
        open=False,
    )


def buka_kolam(kolam: ConnectionPool, dsn: str) -> None:
    """Buka kolam dan tunggu koneksi pertama; gagal -> DatabaseTidakTersedia tanpa kredensial."""
    try:
        kolam.open(wait=True, timeout=WAKTU_KONEK_DETIK)
    except PoolTimeout as exc:
        kolam.close()
        raise DatabaseTidakTersedia(
            f"Database lokal {ringkas_target(dsn)} tidak bisa dihubungi dalam "
            f"{WAKTU_KONEK_DETIK} detik. Periksa service PostgreSQL dan CASING_LOCAL_DATABASE_URL."
        ) from exc


def buka_koneksi(dsn: str) -> "psycopg.Connection[DictRow]":
    """Buka satu koneksi (untuk skrip/test); gagal -> DatabaseTidakTersedia tanpa kredensial."""
    try:
        return psycopg.connect(dsn, row_factory=dict_row, connect_timeout=WAKTU_KONEK_DETIK)
    except psycopg.OperationalError as exc:
        raise DatabaseTidakTersedia(
            f"Database lokal {ringkas_target(dsn)} tidak bisa dihubungi."
        ) from exc


def transaksi(conn: psycopg.Connection) -> AbstractContextManager:
    """Mulai blok transaksi pada `conn`: commit bila sukses, rollback bila ada exception."""
    return conn.transaction()


def kursor(conn: psycopg.Connection) -> "psycopg.Cursor[DictRow]":
    """Kursor yang mengembalikan baris sebagai dict, apa pun row_factory milik `conn`."""
    return conn.cursor(row_factory=dict_row)
