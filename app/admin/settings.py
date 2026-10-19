"""Admin pengaturan aplikasi: konfigurasi berversi (ambang, masa simpan, ruang warna default)."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.admin.deps import butuh_admin_api, butuh_admin_halaman, periksa_origin
from app.auth.model import Pengguna
from app.storage.local import audit_perubahan, konfigurasi
from app.storage.local.skema import KonfigurasiAplikasi
from app.ui.routes import TEMPLATES

router = APIRouter()
NAMA_MENU = "pengaturan"
OBJEK = "konfigurasi"

Admin = Annotated[Pengguna, Depends(butuh_admin_api)]


def _kolam(request: Request):
    """Kolam DB lokal atau 503."""
    kolam = getattr(request.app.state, "db", None)
    if kolam is None:
        raise HTTPException(status_code=503, detail="Database lokal tidak tersedia.")
    return kolam


def peringatan(k: KonfigurasiAplikasi, lama: KonfigurasiAplikasi | None) -> list[str]:
    """Peringatan untuk nilai berisiko (bukan penolakan)."""
    hasil: list[str] = []
    if k.ambang_keyakinan < 0.5:
        hasil.append("Ambang keyakinan di bawah 50%: deteksi ragu bisa lolos sebagai MATCH.")
    if k.izinkan_kurang_dari_default:
        hasil.append("Box kurang lengkap diizinkan: box dengan part hilang bisa lolos.")
    if lama is not None and k.masa_simpan_gambar_hari < lama.masa_simpan_gambar_hari:
        hasil.append(
            f"Gambar lebih lama dari {k.masa_simpan_gambar_hari} hari akan dihapus pada "
            "pembersihan berikutnya."
        )
    return hasil


@router.get("/api/pengaturan")
def ambil_pengaturan(request: Request, _: Admin) -> dict[str, Any]:
    """Konfigurasi terbaru (versi 0 = bawaan) dan 5 perubahan terakhir."""
    kolam = _kolam(request)
    with kolam.connection() as conn:
        versi, data = konfigurasi.ambil_terbaru(conn)
        riwayat = audit_perubahan.daftar(conn, objek=OBJEK, limit=5)
    return {
        "versi": versi,
        "data": data.model_dump(mode="json"),
        "riwayat": [
            {
                "waktu": r["waktu"].isoformat(),
                "oleh": r["oleh"],
                "versi": r["versi_sesudah"],
                "diff": r["detail"].get("diff", {}),
            }
            for r in riwayat
        ],
    }


@router.put("/api/pengaturan", dependencies=[Depends(periksa_origin)])
def simpan_pengaturan(badan: KonfigurasiAplikasi, request: Request, admin: Admin) -> dict:
    """Simpan konfigurasi penuh sebagai versi baru bila ada perubahan; catat diff ke audit."""
    kolam = _kolam(request)
    with kolam.connection() as conn, conn.transaction():
        versi_lama, lama = konfigurasi.ambil_terbaru(conn)
        a, b = lama.model_dump(mode="json"), badan.model_dump(mode="json")
        diff = {k: {"dari": a[k], "ke": b[k]} for k in b if a[k] != b[k]}
        if not diff and versi_lama > 0:
            return {"versi": versi_lama, "berubah": False, "peringatan": peringatan(badan, lama)}
        versi_baru = konfigurasi.simpan_baru(conn, badan, admin.username)
        audit_perubahan.catat(
            conn,
            oleh=admin.username,
            aksi="konfigurasi.simpan",
            objek=OBJEK,
            detail={"diff": diff or {k: {"dari": None, "ke": v} for k, v in b.items()}},
            versi_sebelum=versi_lama or None,
            versi_sesudah=versi_baru,
        )
    return {"versi": versi_baru, "berubah": True, "peringatan": peringatan(badan, lama)}


@router.get("/pengaturan", response_class=HTMLResponse)
def halaman_pengaturan(
    request: Request, pengguna: Annotated[Pengguna, Depends(butuh_admin_halaman)]
) -> HTMLResponse:
    """Halaman admin pengaturan."""
    from app.admin.routes import MENU

    return TEMPLATES.TemplateResponse(
        request,
        "admin/pengaturan.html",
        {"judul": "Pengaturan — Admin", "menu": MENU, "konfig_scan": {}, "pengguna": pengguna},
    )
