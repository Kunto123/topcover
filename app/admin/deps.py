"""Dependency admin: API (401/403 JSON) dan halaman (redirect ke /login)."""

from fastapi import Depends, Request
from fastapi.responses import RedirectResponse

from app.auth.deps import NAMA_COOKIE, butuh_peran, periksa_origin
from app.auth.model import Pengguna, Peran

butuh_admin_api = butuh_peran(Peran.ADMIN)
"""Dependency API admin: 401 tanpa sesi/cookie sah, 403 bila bukan admin."""


class AlihkanKeLogin(Exception):
    """Dilempar dependency halaman admin; ditangkap handler untuk redirect 303 ke /login."""


def butuh_admin_halaman(request: Request) -> Pengguna:
    """Pengguna admin untuk halaman HTML; selain itu AlihkanKeLogin (redirect, bukan 401)."""
    if not request.app.state.settings.auth_wajib:
        return Pengguna("dev", None, Peran.ADMIN, "lokal", "password")
    sesi = request.app.state.sesi
    pengguna = sesi.saat_ini()
    if (
        pengguna is None
        or pengguna.peran is not Peran.ADMIN
        or not sesi.cocok_token(request.cookies.get(NAMA_COOKIE))
    ):
        raise AlihkanKeLogin
    return pengguna


async def handler_alihkan(request: Request, exc: AlihkanKeLogin) -> RedirectResponse:
    """Ubah AlihkanKeLogin menjadi redirect 303 ke /login."""
    return RedirectResponse("/login", status_code=303)


__all__ = [
    "AlihkanKeLogin",
    "Depends",
    "butuh_admin_api",
    "butuh_admin_halaman",
    "handler_alihkan",
    "periksa_origin",
]
