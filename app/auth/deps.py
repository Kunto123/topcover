"""Dependency FastAPI untuk auth: cek Origin, login wajib, dan peran."""

from collections.abc import Callable
from urllib.parse import urlparse

from fastapi import HTTPException, Request

from app.auth.model import Pengguna, Peran

NAMA_COOKIE = "casing_sesi"
METODE_MENGUBAH = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def periksa_origin(request: Request) -> None:
    """Tolak permintaan pengubah dengan header Origin bukan dari host lokal aplikasi (403)."""
    if request.method not in METODE_MENGUBAH:
        return
    origin = request.headers.get("origin")
    if origin is None:
        return
    port = request.app.state.settings.port
    diizinkan = {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}
    if urlparse(origin).netloc not in diizinkan:
        raise HTTPException(status_code=403, detail="Asal permintaan tidak diizinkan.")


def _pengguna_dev() -> Pengguna:
    """Pengguna palsu untuk mode `auth_wajib=False` (hanya dev)."""
    return Pengguna("dev", None, Peran.ADMIN, "lokal", "password")


def butuh_login(request: Request) -> Pengguna:
    """Pengguna aktif dari sesi station; tidak ada -> 401."""
    if not request.app.state.settings.auth_wajib:
        return _pengguna_dev()
    pengguna = request.app.state.sesi.saat_ini()
    if pengguna is None:
        raise HTTPException(status_code=401, detail="Belum login.")
    return pengguna


def butuh_peran(peran: Peran) -> Callable[[Request], Pengguna]:
    """Buat dependency yang mensyaratkan `peran`, sesi aktif, dan cookie sesi yang cocok."""

    def dependency(request: Request) -> Pengguna:
        """401 tanpa sesi/cookie sah, 403 bila peran kurang."""
        if not request.app.state.settings.auth_wajib:
            return _pengguna_dev()
        sesi = request.app.state.sesi
        pengguna = sesi.saat_ini()
        if pengguna is None or not sesi.cocok_token(request.cookies.get(NAMA_COOKIE)):
            raise HTTPException(status_code=401, detail="Belum login.")
        if peran is Peran.ADMIN and pengguna.peran is not Peran.ADMIN:
            raise HTTPException(status_code=403, detail="Butuh peran admin.")
        return pengguna

    return dependency
