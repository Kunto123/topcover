"""Repository `varian_warna`. Tanpa commit; isi JSONB divalidasi pydantic saat tulis dan baca."""

from typing import Any

import psycopg
from psycopg.types.json import Jsonb
from pydantic import ValidationError

from app.storage.local.db import kursor
from app.storage.local.skema import SkemaTidakValid, SpesifikasiVarian


def _muat(baris: dict[str, Any]) -> dict[str, Any]:
    """Validasi ulang `spesifikasi` dari DB; melenceng -> SkemaTidakValid memuat id/nama."""
    try:
        spesifikasi = SpesifikasiVarian.model_validate(baris["spesifikasi"])
    except ValidationError as exc:
        raise SkemaTidakValid(
            f"spesifikasi varian id={baris['id']} nama={baris['nama']!r} tidak valid: {exc}"
        ) from exc
    return {**baris, "spesifikasi": spesifikasi}


def simpan(
    conn: psycopg.Connection, nama: str, spesifikasi: SpesifikasiVarian, oleh: str | None
) -> int:
    """Upsert varian menurut `nama`: baru -> versi 1; ada -> versi naik. Kembalikan id."""
    if not nama.strip():
        raise ValueError("nama varian tidak boleh kosong")
    with kursor(conn) as cur:
        cur.execute(
            "INSERT INTO varian_warna (nama, spesifikasi, diubah_oleh) VALUES (%s, %s, %s)"
            " ON CONFLICT (nama) DO UPDATE SET spesifikasi = EXCLUDED.spesifikasi,"
            " versi = varian_warna.versi + 1, diubah_pada = now(),"
            " diubah_oleh = EXCLUDED.diubah_oleh RETURNING id",
            (nama, Jsonb(spesifikasi.model_dump(mode="json")), oleh),
        )
        baris = cur.fetchone()
    if baris is None:
        raise RuntimeError("upsert varian_warna tidak mengembalikan id")
    return int(baris["id"])


def ambil(conn: psycopg.Connection, nama: str) -> dict[str, Any] | None:
    """Ambil varian berdasarkan `nama` (spesifikasi sudah berupa SpesifikasiVarian), atau None."""
    with kursor(conn) as cur:
        cur.execute("SELECT * FROM varian_warna WHERE nama = %s", (nama,))
        baris = cur.fetchone()
    return _muat(baris) if baris else None


def daftar(conn: psycopg.Connection, hanya_aktif: bool = True) -> list[dict[str, Any]]:
    """Daftar varian urut nama; `hanya_aktif` menyaring yang dinonaktifkan."""
    sql = "SELECT * FROM varian_warna"
    if hanya_aktif:
        sql += " WHERE aktif"
    with kursor(conn) as cur:
        cur.execute(sql + " ORDER BY nama")
        return [_muat(b) for b in cur.fetchall()]


def nonaktifkan(conn: psycopg.Connection, nama: str, oleh: str | None) -> bool:
    """Nonaktifkan varian `nama`; True bila ada baris yang berubah."""
    with kursor(conn) as cur:
        cur.execute(
            "UPDATE varian_warna SET aktif = false, versi = versi + 1, diubah_pada = now(),"
            " diubah_oleh = %s WHERE nama = %s AND aktif",
            (oleh, nama),
        )
        return cur.rowcount > 0


def aktifkan(conn: psycopg.Connection, nama: str, oleh: str | None) -> bool:
    """Aktifkan kembali varian `nama`; True bila ada baris yang berubah."""
    with kursor(conn) as cur:
        cur.execute(
            "UPDATE varian_warna SET aktif = true, versi = versi + 1, diubah_pada = now(),"
            " diubah_oleh = %s WHERE nama = %s AND NOT aktif",
            (oleh, nama),
        )
        return cur.rowcount > 0
