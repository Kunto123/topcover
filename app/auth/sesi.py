"""Sesi station: satu pengguna aktif pada satu waktu (kiosk), dengan batas idle."""

import hmac
import logging
import secrets
import threading
import time
from collections.abc import Callable
from typing import Any

from app.auth.model import Pengguna

logger = logging.getLogger("app.auth.sesi")


class SesiStasiun:
    """Menyimpan pengguna aktif, token cookie (opsional), dan waktu aktivitas terakhir."""

    def __init__(self, idle_menit: float, jam: Callable[[], float] = time.time) -> None:
        """`idle_menit` batas diam; `jam` fungsi waktu (detik) yang bisa diganti di test."""
        self._idle_s = idle_menit * 60
        self._jam = jam
        self._lock = threading.Lock()
        self._pengguna: Pengguna | None = None
        self._token: str | None = None
        self._terakhir = 0.0
        self._pendengar: list[Callable[[dict[str, Any]], None]] = []

    def tambah_pendengar(self, fn: Callable[[dict[str, Any]], None]) -> None:
        """Daftarkan `fn(ringkasan)` yang dipanggil (di luar lock) saat sesi berubah."""
        self._pendengar.append(fn)

    def _ringkasan(self, pengguna: Pengguna | None) -> dict[str, Any]:
        """Ringkasan publik sesi (tanpa token)."""
        if pengguna is None:
            return {"login": False}
        return {
            "login": True,
            "username": pengguna.username,
            "nama": pengguna.tampil,
            "peran": pengguna.peran.value,
            "sumber": pengguna.sumber,
            "via": pengguna.via,
        }

    def _siarkan(self, pengguna: Pengguna | None) -> None:
        """Beritahu pendengar; galat pendengar dicatat, tidak dilempar."""
        ringkasan = self._ringkasan(pengguna)
        for fn in list(self._pendengar):
            try:
                fn(ringkasan)
            except Exception:
                logger.exception("sesi_pendengar_galat")

    def masuk(self, pengguna: Pengguna, *, buat_token: bool) -> str | None:
        """Mulai sesi (menggantikan yang lama); kembalikan token cookie bila `buat_token`."""
        with self._lock:
            self._pengguna = pengguna
            self._token = secrets.token_urlsafe(32) if buat_token else None
            self._terakhir = self._jam()
            token = self._token
        logger.info(
            "sesi_masuk",
            extra={
                "username": pengguna.username,
                "peran": pengguna.peran.value,
                "via": pengguna.via,
            },
        )
        self._siarkan(pengguna)
        return token

    def keluar(self, alasan: str = "keluar") -> None:
        """Akhiri sesi (idempoten); `alasan` hanya untuk log."""
        with self._lock:
            ada = self._pengguna is not None
            self._pengguna = None
            self._token = None
        if ada:
            logger.info("sesi_keluar", extra={"alasan": alasan})
            self._siarkan(None)

    def saat_ini(self) -> Pengguna | None:
        """Pengguna aktif, atau None; sesi yang idle melewati batas otomatis berakhir."""
        with self._lock:
            pengguna = self._pengguna
            kedaluwarsa = pengguna is not None and self._jam() - self._terakhir > self._idle_s
        if kedaluwarsa:
            self.keluar("idle")
            return None
        return pengguna

    def sentuh(self) -> None:
        """Perbarui waktu aktivitas (menunda idle) bila ada sesi."""
        with self._lock:
            if self._pengguna is not None:
                self._terakhir = self._jam()

    def cocok_token(self, token: str | None) -> bool:
        """True bila `token` sama dengan token sesi aktif (perbandingan waktu-konstan)."""
        if not token or self.saat_ini() is None:
            return False
        with self._lock:
            asli = self._token
        return asli is not None and hmac.compare_digest(asli, token)

    def ringkasan(self) -> dict[str, Any]:
        """Ringkasan sesi saat ini untuk API/SSE."""
        return self._ringkasan(self.saat_ini())
