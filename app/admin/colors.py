"""Admin varian warna referensi: daftar, ubah, aktif/nonaktif, dan peringatan tumpang tindih."""

import math
import re
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ValidationError

from app.admin.deps import butuh_admin_api, butuh_admin_halaman, periksa_origin
from app.auth.model import Pengguna
from app.domain.box_rules import VarianWarna, periksa_pemisahan_varian
from app.storage.local import audit_perubahan, varian
from app.storage.local.skema import RuangWarnaNama, SpesifikasiVarian
from app.ui.routes import TEMPLATES

router = APIRouter()
NAMA_MENU = "warna"
# Parser datapart menurunkan varian ke huruf kecil; nama di DB harus sama persis.
POLA_NAMA = re.compile(r"^[a-z0-9_]{1,50}$")

Admin = Annotated[Pengguna, Depends(butuh_admin_api)]


class PermintaanVarian(BaseModel):
    """Badan PUT varian: tiga nilai referensi, toleransi (> 0), dan ruang warna."""

    referensi: tuple[float, float, float]
    toleransi: float
    ruang: RuangWarnaNama = "lab"


def _kolam(request: Request):
    """Kolam DB lokal atau 503."""
    kolam = getattr(request.app.state, "db", None)
    if kolam is None:
        raise HTTPException(status_code=503, detail="Database lokal tidak tersedia.")
    return kolam


def _nama(nama: str) -> str:
    """Normalisasi nama varian ke huruf kecil dan validasi pola; salah -> 422."""
    bersih = nama.strip().lower()
    if not POLA_NAMA.fullmatch(bersih):
        raise HTTPException(
            status_code=422, detail="Nama varian: 1-50 karakter huruf kecil, angka, atau _."
        )
    return bersih


def _ringkas(b: dict[str, Any]) -> dict[str, Any]:
    """Ringkas baris varian untuk JSON."""
    sp: SpesifikasiVarian = b["spesifikasi"]
    return {
        "nama": b["nama"],
        "referensi": list(sp.referensi),
        "toleransi": sp.toleransi,
        "ruang": sp.ruang,
        "aktif": b["aktif"],
        "versi": b["versi"],
        "diubah_pada": b["diubah_pada"].isoformat() if b.get("diubah_pada") else None,
        "diubah_oleh": b.get("diubah_oleh"),
    }


def peringatan_pemisahan(baris: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Peringatan toleransi tumpang tindih antar varian AKTIF se-ruang warna."""
    per_ruang: dict[str, list[VarianWarna]] = {}
    for b in baris:
        if not b["aktif"]:
            continue
        sp: SpesifikasiVarian = b["spesifikasi"]
        per_ruang.setdefault(sp.ruang, []).append(
            VarianWarna(b["nama"], sp.referensi, sp.toleransi, sp.ruang)
        )
    hasil: list[dict[str, Any]] = []
    for ruang, daftar in per_ruang.items():
        for p in periksa_pemisahan_varian(daftar):
            hasil.append(
                {
                    "a": p.a,
                    "b": p.b,
                    "ruang": ruang,
                    "jarak": round(p.jarak, 5),
                    "jumlah_toleransi": round(p.jumlah_toleransi, 5),
                }
            )
    return hasil


@router.get("/api/warna")
def daftar_varian(request: Request, _: Admin, semua: bool = False) -> dict[str, Any]:
    """Daftar varian (aktif saja kecuali `semua=true`) beserta peringatan tumpang tindih."""
    kolam = _kolam(request)
    with kolam.connection() as conn:
        baris = varian.daftar(conn, hanya_aktif=False)
    return {
        "varian": [_ringkas(b) for b in baris if semua or b["aktif"]],
        "peringatan": peringatan_pemisahan(baris),
    }


@router.put("/api/warna/{nama}", dependencies=[Depends(periksa_origin)])
def simpan_varian(nama: str, badan: PermintaanVarian, request: Request, admin: Admin) -> dict:
    """Tambah/ubah varian `nama`; tercatat di audit dalam satu transaksi."""
    nama = _nama(nama)
    if not math.isfinite(badan.toleransi) or badan.toleransi <= 0:
        raise HTTPException(status_code=422, detail="Toleransi harus bilangan hingga > 0.")
    if not all(math.isfinite(x) for x in badan.referensi):
        raise HTTPException(status_code=422, detail="Referensi harus tiga bilangan hingga.")
    try:
        spesifikasi = SpesifikasiVarian(
            referensi=badan.referensi, toleransi=badan.toleransi, ruang=badan.ruang
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc.errors()[0]["msg"])) from exc
    kolam = _kolam(request)
    with kolam.connection() as conn, conn.transaction():
        sebelum = varian.ambil(conn, nama)
        varian.simpan(conn, nama, spesifikasi, admin.username)
        sesudah = varian.ambil(conn, nama)
        audit_perubahan.catat(
            conn,
            oleh=admin.username,
            aksi="varian.simpan",
            objek=f"varian:{nama}",
            detail={
                "sebelum": _ringkas(sebelum) if sebelum else None,
                "sesudah": _ringkas(sesudah) if sesudah else None,
            },
            versi_sebelum=sebelum["versi"] if sebelum else None,
            versi_sesudah=sesudah["versi"] if sesudah else None,
        )
        semua = varian.daftar(conn, hanya_aktif=False)
    return {
        "versi": sesudah["versi"] if sesudah else None,
        "peringatan": peringatan_pemisahan(semua),
    }


def _ubah_aktif(nama: str, request: Request, admin: Pengguna, aktif: bool) -> dict:
    """Aktifkan/nonaktifkan varian dan catat ke audit."""
    nama = _nama(nama)
    kolam = _kolam(request)
    with kolam.connection() as conn, conn.transaction():
        sebelum = varian.ambil(conn, nama)
        if sebelum is None:
            raise HTTPException(status_code=404, detail="Varian tidak ditemukan.")
        fungsi = varian.aktifkan if aktif else varian.nonaktifkan
        berubah = fungsi(conn, nama, admin.username)
        if berubah:
            sesudah = varian.ambil(conn, nama)
            audit_perubahan.catat(
                conn,
                oleh=admin.username,
                aksi="varian.aktifkan" if aktif else "varian.nonaktifkan",
                objek=f"varian:{nama}",
                detail={"aktif": aktif},
                versi_sebelum=sebelum["versi"],
                versi_sesudah=sesudah["versi"] if sesudah else None,
            )
    return {"nama": nama, "aktif": aktif, "berubah": berubah}


@router.post("/api/warna/{nama}/nonaktifkan", dependencies=[Depends(periksa_origin)])
def nonaktifkan_varian(nama: str, request: Request, admin: Admin) -> dict:
    """Nonaktifkan varian (datapart varian ini menjadi VARIAN_TIDAK_DIKENAL)."""
    return _ubah_aktif(nama, request, admin, False)


@router.post("/api/warna/{nama}/aktifkan", dependencies=[Depends(periksa_origin)])
def aktifkan_varian(nama: str, request: Request, admin: Admin) -> dict:
    """Aktifkan kembali varian yang dinonaktifkan."""
    return _ubah_aktif(nama, request, admin, True)


@router.get("/warna", response_class=HTMLResponse)
def halaman_warna(
    request: Request, pengguna: Annotated[Pengguna, Depends(butuh_admin_halaman)]
) -> HTMLResponse:
    """Halaman admin varian warna."""
    from app.admin.routes import MENU

    return TEMPLATES.TemplateResponse(
        request,
        "admin/warna.html",
        {"judul": "Warna — Admin", "menu": MENU, "konfig_scan": {}, "pengguna": pengguna},
    )
