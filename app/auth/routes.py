"""Route auth: login password, logout, sesi, dan halaman /login."""

import logging
from typing import Annotated

import anyio.to_thread
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, StrictStr, StringConstraints

from app.auth.deps import NAMA_COOKIE, butuh_login, periksa_origin
from app.auth.model import Pengguna
from app.ui.routes import TEMPLATES

logger = logging.getLogger("app.auth.routes")

router = APIRouter(prefix="/api/auth", tags=["auth"])
router_halaman = APIRouter(tags=["auth"])

PESAN_SALAH = "Username atau password salah."


class PermintaanLogin(BaseModel):
    """Badan POST /login: username 1-100 karakter, password 1-1024 karakter."""

    username: Annotated[
        StrictStr, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
    ]
    password: Annotated[StrictStr, StringConstraints(min_length=1, max_length=1024)]


@router.post("/login", dependencies=[Depends(periksa_origin)])
async def login(badan: PermintaanLogin, request: Request) -> JSONResponse:
    """Login username/password; sukses memasang cookie sesi."""
    state = request.app.state
    if not state.settings.auth_wajib:
        return JSONResponse({"pesan": "Login dimatikan (mode dev)."}, status_code=200)
    hasil = await anyio.to_thread.run_sync(
        state.layanan_auth.login_password, badan.username, badan.password
    )
    if hasil.sukses and hasil.pengguna is not None:
        token = state.sesi.masuk(hasil.pengguna, buat_token=True)
        respons = JSONResponse(_ringkas(hasil.pengguna))
        respons.set_cookie(NAMA_COOKIE, token or "", httponly=True, samesite="strict", path="/")
        return respons
    if hasil.alasan == "terkunci":
        menit = hasil.sisa_kunci_menit or 1
        return JSONResponse(
            {"pesan": f"Terlalu banyak percobaan gagal. Coba lagi dalam {menit} menit."},
            status_code=429,
            headers={"Retry-After": str(menit * 60)},
        )
    if hasil.alasan == "pabrik_tidak_tersedia":
        return JSONResponse(
            {"pesan": "Database pabrik tidak terjangkau; akun lokal admin tetap bisa masuk."},
            status_code=503,
        )
    if hasil.alasan == "audit_tidak_tersedia":
        return JSONResponse({"pesan": "Database lokal tidak tersedia; login ditolak."}, 503)
    return JSONResponse({"pesan": PESAN_SALAH}, status_code=401)


@router.post("/logout", dependencies=[Depends(periksa_origin)])
async def logout(request: Request) -> JSONResponse:
    """Akhiri sesi station dan hapus cookie."""
    request.app.state.sesi.keluar("logout")
    respons = JSONResponse({"login": False})
    respons.delete_cookie(NAMA_COOKIE, path="/")
    return respons


@router.get("/sesi")
async def sesi(request: Request) -> dict:
    """Ringkasan sesi saat ini (`login` true/false)."""
    return request.app.state.sesi.ringkasan()


@router.get("/saya")
async def saya(pengguna: Annotated[Pengguna, Depends(butuh_login)]) -> dict:
    """Pengguna aktif (401 bila belum login)."""
    return _ringkas(pengguna)


def _ringkas(pengguna: Pengguna) -> dict:
    """Ringkasan publik pengguna."""
    return {
        "username": pengguna.username,
        "nama": pengguna.tampil,
        "peran": pengguna.peran.value,
        "sumber": pengguna.sumber,
    }


@router_halaman.get("/login", response_class=HTMLResponse)
async def halaman_login(request: Request) -> HTMLResponse:
    """Halaman login password."""
    return TEMPLATES.TemplateResponse(
        request, "login.html", {"judul": "Masuk — Verifikasi Casing", "konfig_scan": {}}
    )
