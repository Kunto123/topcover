"""Repository `konfigurasi_aplikasi` berversi: perubahan menambah baris. Tanpa commit."""

import psycopg
from psycopg.errors import UniqueViolation
from psycopg.types.json import Jsonb
from pydantic import ValidationError

from app.storage.local.db import kursor
from app.storage.local.skema import KonfigurasiAplikasi, SkemaTidakValid


def ambil_terbaru(conn: psycopg.Connection) -> tuple[int, KonfigurasiAplikasi]:
    """Konfigurasi versi tertinggi; belum ada -> `(0, default)` tanpa menulis apa pun."""
    with kursor(conn) as cur:
        cur.execute("SELECT versi, data FROM konfigurasi_aplikasi ORDER BY versi DESC LIMIT 1")
        baris = cur.fetchone()
    if baris is None:
        return 0, KonfigurasiAplikasi()
    try:
        return int(baris["versi"]), KonfigurasiAplikasi.model_validate(baris["data"])
    except ValidationError as exc:
        raise SkemaTidakValid(f"konfigurasi versi={baris['versi']} tidak valid: {exc}") from exc


def simpan_baru(
    conn: psycopg.Connection, konfigurasi: KonfigurasiAplikasi, oleh: str | None
) -> int:
    """Simpan sebagai versi berikutnya (max+1), kembalikan versinya; bentrok -> ulang sekali."""
    for percobaan in range(2):
        try:
            with conn.transaction(), kursor(conn) as cur:
                cur.execute("SELECT COALESCE(MAX(versi), 0) + 1 AS v FROM konfigurasi_aplikasi")
                baris = cur.fetchone()
                versi = int(baris["v"]) if baris else 1
                cur.execute(
                    "INSERT INTO konfigurasi_aplikasi (versi, data, dibuat_oleh)"
                    " VALUES (%s, %s, %s)",
                    (versi, Jsonb(konfigurasi.model_dump(mode="json")), oleh),
                )
            return versi
        except UniqueViolation:
            if percobaan == 1:
                raise
    raise RuntimeError("tidak tercapai")
