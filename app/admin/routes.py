"""Shell admin: indeks `/admin` dan penggabungan router tiap layar admin."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.admin import audit, colors, models, settings
from app.admin.deps import butuh_admin_api, butuh_admin_halaman
from app.auth.model import Pengguna
from app.ui.routes import TEMPLATES

MENU = [
    ("Model", "/admin/models"),
    ("Warna", "/admin/warna"),
    ("Pengaturan", "/admin/pengaturan"),
    ("Audit", "/admin/audit"),
]

router_admin = APIRouter(prefix="/admin", tags=["admin"])
router_admin.include_router(models.router)
router_admin.include_router(colors.router)
router_admin.include_router(settings.router)
router_admin.include_router(audit.router)


@router_admin.get("", response_class=HTMLResponse)
async def indeks(
    request: Request, pengguna: Annotated[Pengguna, Depends(butuh_admin_halaman)]
) -> HTMLResponse:
    """Halaman indeks admin berisi tautan ke layar admin."""
    return TEMPLATES.TemplateResponse(
        request,
        "admin/index.html",
        {
            "judul": "Admin — Verifikasi Casing",
            "menu": MENU,
            "konfig_scan": {},
            "pengguna": pengguna,
        },
    )


@router_admin.get("/api/ping")
async def ping(pengguna: Annotated[Pengguna, Depends(butuh_admin_api)]) -> dict:
    """Cek sesi admin (dipakai UI admin dan test): kembalikan username dan peran."""
    return {"username": pengguna.username, "peran": pengguna.peran.value}
