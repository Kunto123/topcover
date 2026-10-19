"""Repository `hasil_pemeriksaan`. Fungsi menerima `conn` dan TIDAK me-commit (syarat CV-4)."""

from datetime import datetime
from typing import Any

import psycopg
from psycopg.errors import UniqueViolation
from psycopg.types.json import Jsonb

from app.core.reasons import Verdict
from app.storage.local.db import kursor
from app.storage.local.skema import RekamanHasil

LIMIT_MAKS = 1000


class CycleIdSudahAda(RuntimeError):
    """Sudah ada rekaman dengan `cycle_id` yang sama (satu siklus hanya boleh satu rekaman)."""


def _harus_aware(nama: str, nilai: datetime | None) -> None:
    """Tolak datetime naive pada parameter `nama`."""
    if nilai is not None and nilai.tzinfo is None:
        raise ValueError(f"{nama} harus timezone-aware")


def simpan(conn: psycopg.Connection, rekaman: RekamanHasil) -> int:
    """Simpan `rekaman`, kembalikan id baris; `cycle_id` ganda -> CycleIdSudahAda. Tanpa commit."""
    try:
        with (
            conn.transaction(),
            kursor(conn) as cur,
        ):  # savepoint: kegagalan tak meracuni transaksi luar
            cur.execute(
                "INSERT INTO hasil_pemeriksaan (cycle_id, datapart, varian_warna, verdict,"
                " reason_code, operator, waktu_scan, durasi_total_ms, tahap_ms, path_gambar,"
                " detail_part)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (
                    rekaman.cycle_id,
                    rekaman.datapart,
                    rekaman.varian_warna,
                    rekaman.verdict.value,
                    rekaman.reason_code.value if rekaman.reason_code else None,
                    rekaman.operator,
                    rekaman.waktu_scan,
                    rekaman.durasi_total_ms,
                    Jsonb(rekaman.tahap_ms),
                    rekaman.path_gambar,
                    Jsonb([d.model_dump(mode="json") for d in rekaman.detail_part]),
                ),
            )
            baris = cur.fetchone()
    except UniqueViolation as exc:
        raise CycleIdSudahAda(f"cycle_id {rekaman.cycle_id!r} sudah punya rekaman") from exc
    if baris is None:
        raise RuntimeError("INSERT hasil_pemeriksaan tidak mengembalikan id")
    return int(baris["id"])


def ambil_by_cycle_id(conn: psycopg.Connection, cycle_id: str) -> dict[str, Any] | None:
    """Ambil satu rekaman berdasarkan `cycle_id`, atau None."""
    with kursor(conn) as cur:
        cur.execute("SELECT * FROM hasil_pemeriksaan WHERE cycle_id = %s", (cycle_id,))
        return cur.fetchone()


def hitung_match(conn: psycopg.Connection, sejak: datetime, sampai: datetime | None = None) -> int:
    """Hitung rekaman MATCH dengan `sejak <= waktu_selesai < sampai` (counter dari data lokal)."""
    _harus_aware("sejak", sejak)
    _harus_aware("sampai", sampai)
    sql = (
        "SELECT count(*) AS n FROM hasil_pemeriksaan"
        " WHERE verdict = 'match' AND waktu_selesai >= %s"
    )
    params: list[Any] = [sejak]
    if sampai is not None:
        sql += " AND waktu_selesai < %s"
        params.append(sampai)
    with kursor(conn) as cur:
        cur.execute(sql, params)
        baris = cur.fetchone()
    return int(baris["n"]) if baris else 0


def cari(
    conn: psycopg.Connection,
    *,
    verdict: Verdict | None = None,
    sejak: datetime | None = None,
    sampai: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Cari rekaman (terbaru dulu) dengan filter opsional; `limit` 1..1000, `offset` >= 0."""
    if not 1 <= limit <= LIMIT_MAKS:
        raise ValueError(f"limit harus 1..{LIMIT_MAKS}, dapat {limit}")
    if offset < 0:
        raise ValueError("offset tidak boleh negatif")
    _harus_aware("sejak", sejak)
    _harus_aware("sampai", sampai)
    kondisi: list[str] = []
    params: list[Any] = []
    if verdict is not None:
        kondisi.append("verdict = %s")
        params.append(verdict.value)
    if sejak is not None:
        kondisi.append("waktu_selesai >= %s")
        params.append(sejak)
    if sampai is not None:
        kondisi.append("waktu_selesai < %s")
        params.append(sampai)
    where = f" WHERE {' AND '.join(kondisi)}" if kondisi else ""
    sql = (
        f"SELECT * FROM hasil_pemeriksaan{where}"
        " ORDER BY waktu_selesai DESC, id DESC LIMIT %s OFFSET %s"
    )
    with kursor(conn) as cur:
        cur.execute(sql, [*params, limit, offset])
        return cur.fetchall()


def perbarui_durasi(
    conn: psycopg.Connection,
    rekaman_id: int,
    durasi_total_ms: int,
    tahap_ms: dict[str, int],
) -> bool:
    """Perbarui durasi total dan rincian tahap rekaman LOKAL (pabrik tidak ikut diperbarui).

    Dipanggil setelah print supaya durasi mencakup simpan dan print. Tanpa commit.
    """
    if durasi_total_ms < 0:
        raise ValueError("durasi_total_ms tidak boleh negatif")
    with kursor(conn) as cur:
        cur.execute(
            "UPDATE hasil_pemeriksaan SET durasi_total_ms = %s, tahap_ms = %s WHERE id = %s",
            (durasi_total_ms, Jsonb(tahap_ms), rekaman_id),
        )
        return cur.rowcount > 0
