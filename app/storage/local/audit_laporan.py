"""Query laporan audit SPV: NOT_MATCH lengkap + sampel MATCH acak deterministik, dan ringkasan.

Semua parameter lewat placeholder. Tanpa commit.
"""

from datetime import datetime, timedelta
from typing import Any

import psycopg

from app.storage.local.db import kursor

RENTANG_MAKS_HARI = 92
SAMPEL_MATCH_MAKS = 500
LIMIT_NOT_MATCH = 5000
BATAS_DETIK_SIKLUS_MS = 10_000
TANPA_VARIAN = "(tidak tercatat)"

KOLOM = (
    "id, cycle_id, waktu_scan, waktu_selesai, datapart, varian_warna, verdict, reason_code,"
    " operator, durasi_total_ms, tahap_ms, path_gambar, gambar_dibersihkan, detail_part"
)


def _periksa_rentang(sejak: datetime, sampai: datetime) -> None:
    """Aware, urut, dan tidak lebih dari 92 hari."""
    if sejak.tzinfo is None or sampai.tzinfo is None:
        raise ValueError("sejak/sampai harus timezone-aware")
    if sampai <= sejak:
        raise ValueError("sampai harus setelah sejak")
    if sampai - sejak > timedelta(days=RENTANG_MAKS_HARI):
        raise ValueError(f"rentang maksimal {RENTANG_MAKS_HARI} hari")


def daftar_audit(
    conn: psycopg.Connection,
    *,
    sejak: datetime,
    sampai: datetime,
    sampel_match: int,
    seed: str,
    varian: str | None = None,
    limit_not_match: int = LIMIT_NOT_MATCH,
) -> tuple[list[dict[str, Any]], bool]:
    """Kembalikan (baris terbaru dulu, terpotong). NOT_MATCH semua; MATCH acak per `seed`."""
    _periksa_rentang(sejak, sampai)
    if not 0 <= sampel_match <= SAMPEL_MATCH_MAKS:
        raise ValueError(f"sampel_match harus 0..{SAMPEL_MATCH_MAKS}")
    kondisi = "waktu_selesai >= %s AND waktu_selesai < %s"
    params: list[Any] = [sejak, sampai]
    if varian is not None:
        kondisi += " AND varian_warna = %s"
        params.append(varian)
    with kursor(conn) as cur:
        cur.execute(
            f"SELECT {KOLOM} FROM hasil_pemeriksaan WHERE {kondisi} AND verdict = 'not_match'"
            " ORDER BY waktu_selesai DESC, id DESC LIMIT %s",
            [*params, limit_not_match + 1],
        )
        nm = cur.fetchall()
        terpotong = len(nm) > limit_not_match
        nm = nm[:limit_not_match]
        mt: list[dict[str, Any]] = []
        if sampel_match:
            cur.execute(
                f"SELECT {KOLOM} FROM hasil_pemeriksaan WHERE {kondisi} AND verdict = 'match'"
                " ORDER BY md5(cycle_id || %s), id LIMIT %s",
                [*params, seed, sampel_match],
            )
            mt = cur.fetchall()
    baris = sorted([*nm, *mt], key=lambda b: (b["waktu_selesai"], b["id"]), reverse=True)
    return baris, terpotong


def ringkasan(conn: psycopg.Connection, *, sejak: datetime, sampai: datetime) -> dict[str, Any]:
    """Metrik pilot: MATCH/NOT_MATCH, per alasan, per varian, durasi, dan rata-rata tahap."""
    _periksa_rentang(sejak, sampai)
    rentang = [sejak, sampai]
    with kursor(conn) as cur:
        cur.execute(
            "SELECT count(*) AS total,"
            " count(*) FILTER (WHERE verdict = 'match') AS match,"
            " count(*) FILTER (WHERE verdict = 'not_match') AS not_match,"
            " count(durasi_total_ms) AS n_durasi,"
            " count(*) FILTER (WHERE durasi_total_ms <= %s) AS dalam_batas,"
            " percentile_cont(0.5) WITHIN GROUP (ORDER BY durasi_total_ms) AS p50,"
            " percentile_cont(0.95) WITHIN GROUP (ORDER BY durasi_total_ms) AS p95"
            " FROM hasil_pemeriksaan WHERE waktu_selesai >= %s AND waktu_selesai < %s",
            [BATAS_DETIK_SIKLUS_MS, *rentang],
        )
        r = cur.fetchone() or {}
        cur.execute(
            "SELECT reason_code, count(*) AS n FROM hasil_pemeriksaan"
            " WHERE waktu_selesai >= %s AND waktu_selesai < %s AND reason_code IS NOT NULL"
            " GROUP BY reason_code ORDER BY n DESC",
            rentang,
        )
        per_alasan = {b["reason_code"]: int(b["n"]) for b in cur.fetchall()}
        cur.execute(
            "SELECT coalesce(varian_warna, %s) AS varian,"
            " count(*) FILTER (WHERE verdict = 'match') AS match,"
            " count(*) FILTER (WHERE verdict = 'not_match') AS not_match"
            " FROM hasil_pemeriksaan WHERE waktu_selesai >= %s AND waktu_selesai < %s"
            " GROUP BY 1 ORDER BY 1",
            [TANPA_VARIAN, *rentang],
        )
        per_varian = [
            {"varian": b["varian"], "match": int(b["match"]), "not_match": int(b["not_match"])}
            for b in cur.fetchall()
        ]
        cur.execute(
            "SELECT t.k AS tahap, round(avg(t.v::numeric)) AS rata"
            " FROM hasil_pemeriksaan h, jsonb_each_text(h.tahap_ms) AS t(k, v)"
            " WHERE h.waktu_selesai >= %s AND h.waktu_selesai < %s AND t.v ~ '^[0-9]+$'"
            " GROUP BY t.k ORDER BY t.k",
            rentang,
        )
        tahap = {b["tahap"]: int(b["rata"]) for b in cur.fetchall()}
    total, n_durasi = int(r.get("total", 0)), int(r.get("n_durasi", 0))
    return {
        "total": total,
        "match": int(r.get("match", 0)),
        "not_match": int(r.get("not_match", 0)),
        "persen_match": round(100 * int(r.get("match", 0)) / total, 1) if total else None,
        "per_alasan": per_alasan,
        "per_varian": per_varian,
        "durasi": {
            "n": n_durasi,
            "tanpa_durasi": total - n_durasi,
            "persen_dalam_10_detik": round(100 * int(r.get("dalam_batas", 0)) / n_durasi, 1)
            if n_durasi
            else None,
            "p50_ms": None if r.get("p50") is None else int(r["p50"]),
            "p95_ms": None if r.get("p95") is None else int(r["p95"]),
        },
        "rata_tahap_ms": tahap,
    }
