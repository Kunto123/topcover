"""Admin audit SPV: daftar (NOT_MATCH + sampel MATCH), ringkasan metrik, ekspor CSV, dan gambar."""

import csv
import io
import re
import secrets
from collections.abc import Iterator
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse

from app.admin.deps import butuh_admin_api, butuh_admin_halaman
from app.auth.model import Pengguna
from app.core.reasons import REASON_DESCRIPTIONS, ReasonCode
from app.storage.local import audit_laporan, hasil
from app.ui.routes import TEMPLATES

router = APIRouter()
NAMA_MENU = "audit"

Admin = Annotated[Pengguna, Depends(butuh_admin_api)]
POLA_SEED = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
POLA_VARIAN = re.compile(r"^[a-z0-9_]{1,50}$")
POLA_CYCLE_ID = re.compile(r"^[0-9a-zA-Z_-]{1,64}$")
AWAL_RUMUS = ("=", "+", "-", "@", "\t", "\r")
KOLOM_CSV = [
    "waktu_selesai", "cycle_id", "datapart", "varian", "verdict", "alasan", "alasan_teks",
    "operator", "durasi_ms", "part", "gambar_tersedia",
]  # fmt: skip


def _kolam(request: Request):
    """Kolam DB lokal atau 503."""
    kolam = getattr(request.app.state, "db", None)
    if kolam is None:
        raise HTTPException(status_code=503, detail="Database lokal tidak tersedia.")
    return kolam


def _rentang(mulai: str | None, sampai: str | None) -> tuple[datetime, datetime]:
    """Ubah tanggal lokal `YYYY-MM-DD` menjadi [00:00 mulai, 00:00 setelah sampai) aware."""
    try:
        d1 = date.fromisoformat(mulai) if mulai else date.today()
        d2 = date.fromisoformat(sampai) if sampai else d1
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Tanggal harus berformat YYYY-MM-DD.") from exc
    awal = datetime.combine(d1, time.min).astimezone()
    akhir = datetime.combine(d2 + timedelta(days=1), time.min).astimezone()
    if akhir <= awal:
        raise HTTPException(status_code=422, detail="Tanggal sampai harus sama/setelah mulai.")
    if akhir - awal > timedelta(days=audit_laporan.RENTANG_MAKS_HARI):
        raise HTTPException(
            status_code=422, detail=f"Rentang maksimal {audit_laporan.RENTANG_MAKS_HARI} hari."
        )
    return awal, akhir


def _parameter(seed: str | None, sampel_match: int, varian: str | None) -> tuple[str, str | None]:
    """Validasi seed/sampel/varian; seed kosong dibangkitkan server."""
    if not 0 <= sampel_match <= audit_laporan.SAMPEL_MATCH_MAKS:
        raise HTTPException(
            status_code=422, detail=f"sampel_match harus 0..{audit_laporan.SAMPEL_MATCH_MAKS}."
        )
    if seed and not POLA_SEED.fullmatch(seed):
        raise HTTPException(status_code=422, detail="seed hanya huruf/angka/_/-, maks 64.")
    if varian and not POLA_VARIAN.fullmatch(varian):
        raise HTTPException(status_code=422, detail="varian tidak valid.")
    return seed or secrets.token_hex(4), varian or None


def _alasan_teks(kode: str | None) -> str | None:
    """Deskripsi Indonesia untuk kode alasan, atau kodenya bila tidak dikenal."""
    if kode is None:
        return None
    try:
        return REASON_DESCRIPTIONS[ReasonCode(kode)]
    except ValueError:
        return kode


def _baris_json(b: dict[str, Any]) -> dict[str, Any]:
    """Bentuk JSON satu baris audit (tanpa path_gambar mentah)."""
    ada_gambar = bool(b["path_gambar"]) and not b["gambar_dibersihkan"]
    return {
        "cycle_id": b["cycle_id"],
        "waktu_scan": b["waktu_scan"].isoformat(),
        "waktu_selesai": b["waktu_selesai"].isoformat(),
        "datapart": b["datapart"],
        "varian": b["varian_warna"],
        "verdict": b["verdict"],
        "alasan": b["reason_code"],
        "alasan_teks": _alasan_teks(b["reason_code"]),
        "operator": b["operator"],
        "durasi_ms": b["durasi_total_ms"],
        "tahap_ms": b["tahap_ms"],
        "detail_part": b["detail_part"],
        "gambar_dibersihkan": bool(b["gambar_dibersihkan"]),
        "gambar_url": f"/admin/api/audit/gambar/{b['cycle_id']}" if ada_gambar else None,
    }


def _aman_csv(nilai: Any) -> str:
    """Teks sel CSV; awalan rumus (= + - @ tab CR) diberi `'` agar tidak dieksekusi Excel."""
    teks = "" if nilai is None else str(nilai)
    return "'" + teks if teks.startswith(AWAL_RUMUS) else teks


def _ringkas_part(detail: list[dict[str, Any]]) -> str:
    """Ringkas rincian part: `kelas:keyakinan:jarak;...`."""
    return ";".join(f"{p.get('kelas')}:{p.get('keyakinan')}:{p.get('jarak')}" for p in detail or [])


@router.get("/api/audit")
def daftar(
    request: Request,
    _: Admin,
    mulai: str | None = None,
    sampai: str | None = None,
    sampel_match: int = 50,
    seed: str | None = None,
    varian: str | None = None,
) -> dict[str, Any]:
    """NOT_MATCH lengkap + sampel MATCH acak (seed dikembalikan agar sampel dapat diulang)."""
    awal, akhir = _rentang(mulai, sampai)
    seed_pakai, varian_pakai = _parameter(seed, sampel_match, varian)
    with _kolam(request).connection() as conn:
        baris, terpotong = audit_laporan.daftar_audit(
            conn, sejak=awal, sampai=akhir, sampel_match=sampel_match, seed=seed_pakai,
            varian=varian_pakai,
        )  # fmt: skip
        ring = audit_laporan.ringkasan(conn, sejak=awal, sampai=akhir)
    return {
        "seed": seed_pakai,
        "terpotong": terpotong,
        "ringkasan_singkat": {k: ring[k] for k in ("total", "match", "not_match")},
        "baris": [_baris_json(b) for b in baris],
    }


@router.get("/api/audit/ringkasan")
def ringkasan(
    request: Request, _: Admin, mulai: str | None = None, sampai: str | None = None
) -> dict[str, Any]:
    """Metrik pilot untuk rentang tanggal."""
    awal, akhir = _rentang(mulai, sampai)
    with _kolam(request).connection() as conn:
        return audit_laporan.ringkasan(conn, sejak=awal, sampai=akhir)


@router.get("/api/audit/export.csv")
def ekspor_csv(
    request: Request,
    _: Admin,
    mulai: str | None = None,
    sampai: str | None = None,
    sampel_match: int = 50,
    seed: str | None = None,
    varian: str | None = None,
) -> StreamingResponse:
    """Ekspor CSV (UTF-8 BOM) dengan parameter yang sama seperti daftar audit."""
    awal, akhir = _rentang(mulai, sampai)
    seed_pakai, varian_pakai = _parameter(seed, sampel_match, varian)
    with _kolam(request).connection() as conn:
        baris, _terpotong = audit_laporan.daftar_audit(
            conn, sejak=awal, sampai=akhir, sampel_match=sampel_match, seed=seed_pakai,
            varian=varian_pakai,
        )  # fmt: skip

    def alir() -> Iterator[bytes]:
        """Hasilkan CSV bertahap per 500 baris."""
        buf = io.StringIO()
        penulis = csv.writer(buf)
        penulis.writerow(KOLOM_CSV)
        yield b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")
        for i in range(0, len(baris), 500):
            buf.seek(0)
            buf.truncate()
            for b in baris[i : i + 500]:
                j = _baris_json(b)
                penulis.writerow(
                    [
                        _aman_csv(x)
                        for x in (
                            j["waktu_selesai"], j["cycle_id"], j["datapart"], j["varian"],
                            j["verdict"], j["alasan"], j["alasan_teks"], j["operator"],
                            j["durasi_ms"], _ringkas_part(j["detail_part"]),
                            "ya" if j["gambar_url"] else "tidak",
                        )
                    ]
                )  # fmt: skip
            yield buf.getvalue().encode("utf-8")

    nama = f"audit_{awal.date()}_{(akhir - timedelta(days=1)).date()}.csv"
    return StreamingResponse(
        alir(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nama}"'},
    )


@router.get("/api/audit/gambar/{cycle_id}")
def gambar(cycle_id: str, request: Request, _: Admin) -> Response:
    """Sajikan gambar rekaman bila masih ada, di dalam `image_dir`, dan belum dibersihkan."""
    tidak_ada = HTTPException(status_code=404, detail="Gambar tidak tersedia.")
    if not POLA_CYCLE_ID.fullmatch(cycle_id):
        raise tidak_ada
    with _kolam(request).connection() as conn:
        rekaman = hasil.ambil_by_cycle_id(conn, cycle_id)
    if rekaman is None or rekaman["gambar_dibersihkan"] or not rekaman["path_gambar"]:
        raise tidak_ada
    akar = Path(request.app.state.settings.image_dir)
    try:
        p = Path(rekaman["path_gambar"])
        if p.is_symlink() or p.suffix != ".jpg" or not p.is_file():
            raise tidak_ada
        if not p.resolve().is_relative_to(akar.resolve()):
            raise tidak_ada
    except OSError as exc:
        raise tidak_ada from exc
    return FileResponse(p, media_type="image/jpeg", headers={"Cache-Control": "private, no-store"})


@router.get("/audit", response_class=HTMLResponse)
def halaman_audit(
    request: Request, pengguna: Annotated[Pengguna, Depends(butuh_admin_halaman)]
) -> HTMLResponse:
    """Halaman admin audit SPV."""
    from app.admin.routes import MENU

    return TEMPLATES.TemplateResponse(
        request,
        "admin/audit.html",
        {"judul": "Audit — Admin", "menu": MENU, "konfig_scan": {}, "pengguna": pengguna},
    )
