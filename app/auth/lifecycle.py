"""Pemasangan auth ke aplikasi: sesi station, layanan login, `status_login`, dan penangan RFID."""

import logging
from typing import Any

from fastapi import FastAPI

from app.auth.layanan import LayananAuth
from app.auth.model import HasilLogin, Pengguna, Peran
from app.auth.routes import router_halaman
from app.auth.sesi import SesiStasiun
from app.core.config import Settings

logger = logging.getLogger("app.auth.lifecycle")

PESAN_RFID = {
    "tidak_dikenal": "Kartu tidak dikenal atau akun nonaktif.",
    "pabrik_tidak_tersedia": "Database pabrik tidak terjangkau; login RFID tidak bisa.",
    "audit_tidak_tersedia": "Database lokal tidak tersedia; login ditolak.",
    "kredensial_salah": "Kartu ditolak.",
    "terkunci": "Akun terkunci sementara.",
}
IDLE_DEV_MENIT = 10**6


def _hasil_rfid(hasil: HasilLogin) -> dict[str, Any]:
    """Susun balasan RFID untuk UI (tanpa data sensitif)."""
    if hasil.sukses and hasil.pengguna is not None:
        return {"sukses": True, "nama": hasil.pengguna.tampil, "peran": hasil.pengguna.peran.value}
    return {"sukses": False, "pesan": PESAN_RFID.get(hasil.alasan, "Login gagal.")}


def pasang(app: FastAPI, settings: Settings) -> None:
    """Pasang sesi/layanan auth; menimpa `status_login` dan `penangan_rfid` milik CV-6."""
    # Sesi yang berakhir di tengah siklus tidak membatalkan siklus itu; hasilnya tetap atas
    # nama operator yang memulai (nama diambil saat capture dimulai oleh CV-12).
    app.include_router(router_halaman)
    wajib = settings.auth_wajib
    sesi = SesiStasiun(settings.sesi_idle_menit if wajib else IDLE_DEV_MENIT)
    layanan = LayananAuth(
        lambda: getattr(app.state, "db", None),
        lambda: getattr(app.state, "pabrik", None),
        settings,
    )
    app.state.sesi = sesi
    app.state.layanan_auth = layanan
    penyiar = app.state.penyiar
    sesi.tambah_pendengar(lambda ringkasan: penyiar.publish("sesi", ringkasan))
    app.state.siklus.tambah_pendengar(lambda _peristiwa: sesi.sentuh())

    if not wajib:
        logger.warning("auth_dimatikan_mode_dev")
        sesi.masuk(
            Pengguna("dev", "Operator Dev", Peran.OPERATOR, "lokal", "password"), buat_token=False
        )
        app.state.status_login = lambda: True
        return

    def penangan_rfid(uid: str) -> dict[str, Any]:
        """Login RFID (jalan di thread); sukses memasang sesi operator tanpa cookie."""
        hasil = layanan.login_rfid(uid)
        if hasil.sukses and hasil.pengguna is not None:
            sesi.masuk(hasil.pengguna, buat_token=False)
        return _hasil_rfid(hasil)

    app.state.status_login = lambda: sesi.saat_ini() is not None
    app.state.penangan_rfid = penangan_rfid
