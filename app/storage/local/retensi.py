"""Repository retensi gambar: kandidat kedaluwarsa, penandaan, dan cek rekaman. Tanpa commit."""

from datetime import datetime
from typing import Any

import psycopg

from app.storage.local.db import kursor


def _aware(nama: str, nilai: datetime) -> None:
    """Tolak datetime naive."""
    if nilai.tzinfo is None:
        raise ValueError(f"{nama} harus timezone-aware")


def kedaluwarsa(
    conn: psycopg.Connection, sebelum: datetime, limit: int = 200
) -> list[dict[str, Any]]:
    """Rekaman yang gambarnya belum dibersihkan dan `waktu_selesai < sebelum` (terlama dulu)."""
    _aware("sebelum", sebelum)
    if not 1 <= limit <= 5000:
        raise ValueError("limit harus 1..5000")
    with kursor(conn) as cur:
        cur.execute(
            "SELECT id, cycle_id, path_gambar FROM hasil_pemeriksaan"
            " WHERE gambar_dibersihkan = false AND path_gambar IS NOT NULL AND waktu_selesai < %s"
            " ORDER BY waktu_selesai, id LIMIT %s",
            (sebelum, limit),
        )
        return cur.fetchall()


def tandai_dibersihkan(conn: psycopg.Connection, ids: list[int]) -> int:
    """Tandai `gambar_dibersihkan = true` untuk `ids` (idempoten); kembalikan jumlah berubah."""
    if not ids:
        return 0
    with kursor(conn) as cur:
        cur.execute(
            "UPDATE hasil_pemeriksaan SET gambar_dibersihkan = true"
            " WHERE id = ANY(%s) AND gambar_dibersihkan = false",
            (ids,),
        )
        return cur.rowcount


def ada_rekaman(conn: psycopg.Connection, cycle_ids: list[str]) -> set[str]:
    """Subset `cycle_ids` yang sudah punya rekaman (untuk sapuan gambar yatim)."""
    if not cycle_ids:
        return set()
    with kursor(conn) as cur:
        cur.execute("SELECT cycle_id FROM hasil_pemeriksaan WHERE cycle_id = ANY(%s)", (cycle_ids,))
        return {b["cycle_id"] for b in cur.fetchall()}
