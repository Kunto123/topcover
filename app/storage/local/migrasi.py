"""Runner migrasi SQL berversi: `migrations/NNN_nama.sql`, checksum SHA-256, satu transaksi."""

import hashlib
import logging
import re
from pathlib import Path

import psycopg

from app.storage.local.db import kursor

logger = logging.getLogger("app.storage.migrasi")

DIR_MIGRASI = Path(__file__).resolve().parents[3] / "migrations"
POLA_BERKAS = re.compile(r"(\d{3})_[a-z0-9_]+\.sql")
LOCK_ID = 7_450_001  # kunci advisory agar dua proses tidak bermigrasi bersamaan


class MigrasiBerubah(RuntimeError):
    """Berkas migrasi yang sudah diterapkan diubah (checksum berbeda); jangan edit migrasi lama."""


def terapkan_migrasi(conn: psycopg.Connection, direktori: Path = DIR_MIGRASI) -> list[str]:
    """Terapkan migrasi yang belum tercatat (semuanya dalam satu transaksi); kembalikan versinya.

    Nama berkas tidak sesuai pola -> ValueError. Checksum berkas lama berubah -> MigrasiBerubah.
    """
    berkas = sorted(Path(direktori).glob("*.sql"))
    for p in berkas:
        if not POLA_BERKAS.fullmatch(p.name):
            raise ValueError(f"nama berkas migrasi tidak valid: {p.name!r} (pola NNN_nama.sql)")

    baru: list[str] = []
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK_ID,))
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " versi text PRIMARY KEY, nama text NOT NULL, checksum text NOT NULL,"
            " diterapkan_pada timestamptz NOT NULL DEFAULT now())"
        )
        with kursor(conn) as cur:
            cur.execute("SELECT versi, checksum FROM schema_migrations")
            tercatat = {r["versi"]: r["checksum"] for r in cur.fetchall()}

        for p in berkas:
            isi = p.read_bytes()
            checksum = hashlib.sha256(isi).hexdigest()
            versi = p.name[:3]
            if versi in tercatat:
                if tercatat[versi] != checksum:
                    raise MigrasiBerubah(
                        f"Migrasi {p.name} sudah diterapkan tetapi isinya berubah; "
                        "buat migrasi baru, jangan edit yang lama."
                    )
                continue
            conn.execute(isi.decode("utf-8"))  # tanpa parameter: banyak pernyataan diizinkan
            conn.execute(
                "INSERT INTO schema_migrations (versi, nama, checksum) VALUES (%s, %s, %s)",
                (versi, p.name, checksum),
            )
            baru.append(versi)
            logger.info("db_migrasi_diterapkan", extra={"versi": versi, "nama": p.name})
    return baru
