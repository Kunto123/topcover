"""Logika login: akun lokal (admin) dan operator/admin pabrik, batas gagal, dan audit.

Semua method sinkron/blocking: panggil lewat thread. Password dan UID RFID mentah tidak pernah
masuk log atau audit.
"""

import hashlib
import logging
import math
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from psycopg_pool import ConnectionPool

from app.auth.hash import PANJANG_MAKS, hash_dummy, hash_password, perlu_rehash, verifikasi_password
from app.auth.kredensial import VerifikatorKredensial, VerifikatorSementara
from app.auth.model import HasilLogin, Pengguna, Peran
from app.core.config import Settings
from app.storage.factory.port import OperatorPabrik, PabrikError, PortPabrik
from app.storage.local import akun_lokal, audit_auth

logger = logging.getLogger("app.auth.layanan")

USERNAME_MAKS = 100
WAKTU_KONEKSI_DETIK = 2


class _AuditGagal(Exception):
    """Penulisan audit gagal (internal); login harus ditolak."""


def peran_dari_pabrik(nilai: str | None) -> Peran:
    """Petakan nilai kolom peran pabrik: `admin` (tak peka huruf) -> ADMIN, selain itu OPERATOR."""
    if nilai is not None and nilai.strip().lower() == "admin":
        return Peran.ADMIN
    return Peran.OPERATOR


class LayananAuth:
    """Login password/RFID. Dependensi diambil lewat fungsi agar bisa tersedia setelah start."""

    def __init__(
        self,
        ambil_kolam: Callable[[], ConnectionPool | None],
        ambil_pabrik: Callable[[], PortPabrik | None],
        settings: Settings,
        verifikator: VerifikatorKredensial | None = None,
        jam: Callable[[], float] = time.time,
    ) -> None:
        """`ambil_kolam`/`ambil_pabrik` mengembalikan dependensi saat ini (atau None)."""
        self._ambil_kolam = ambil_kolam
        self._ambil_pabrik = ambil_pabrik
        self._maks_gagal = settings.login_maks_gagal
        self._kunci_menit = settings.login_kunci_menit
        self._verifikator = verifikator or VerifikatorSementara()
        self._jam = jam

    def _sekarang(self) -> datetime:
        """Waktu sekarang (aware, UTC) menurut `jam`."""
        return datetime.fromtimestamp(self._jam(), UTC)

    def _audit(
        self,
        kolam: ConnectionPool,
        *,
        username: str | None,
        sumber: str,
        hasil: str,
        peran: str | None = None,
        alasan: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        """Tulis satu baris audit di transaksinya sendiri; gagal -> _AuditGagal."""
        try:
            with kolam.connection(timeout=WAKTU_KONEKSI_DETIK) as conn:
                audit_auth.catat(
                    conn,
                    username=username,
                    sumber=sumber,
                    hasil=hasil,
                    peran=peran,
                    alasan=alasan,
                    detail=detail,
                )
        except psycopg.Error as exc:
            logger.error("audit_gagal_ditulis", extra={"galat": type(exc).__name__})
            raise _AuditGagal from exc

    def _status_kunci(self, kolam: ConnectionPool, username: str) -> int | None:
        """Sisa menit kunci bila `username` terkunci, atau None."""
        sekarang = self._sekarang()
        jendela = timedelta(minutes=self._kunci_menit)
        with kolam.connection(timeout=WAKTU_KONEKSI_DETIK) as conn:
            jumlah, terakhir = audit_auth.gagal_beruntun(conn, username, sekarang - jendela)
        if jumlah >= self._maks_gagal and terakhir is not None and terakhir + jendela > sekarang:
            sisa = math.ceil((terakhir + jendela - sekarang).total_seconds() / 60)
            return min(self._kunci_menit, max(1, sisa))
        return None

    def _coba_lokal(self, kolam: ConnectionPool, username: str, password: str) -> tuple[bool, bool]:
        """Periksa akun lokal; kembalikan (cocok, akun_ada_dan_aktif). Waktu disamakan."""
        with kolam.connection(timeout=WAKTU_KONEKSI_DETIK) as conn:
            akun = akun_lokal.ambil(conn, username)
        if akun is None or not akun["aktif"]:
            verifikasi_password(password, hash_dummy())
            return False, False
        if not verifikasi_password(password, akun["password_hash"]):
            return False, True
        if perlu_rehash(akun["password_hash"]):
            try:
                with kolam.connection(timeout=WAKTU_KONEKSI_DETIK) as conn:
                    akun_lokal.ganti_hash(conn, username, hash_password(password))
            except psycopg.Error:
                logger.warning("rehash_gagal")
        return True, True

    def _coba_pabrik(
        self, pabrik: PortPabrik, username: str, password: str
    ) -> tuple[OperatorPabrik | None, str]:
        """Periksa operator pabrik; kembalikan (operator|None, status ok/salah/nonaktif/mati)."""
        try:
            op = pabrik.ambil_operator(username=username)
        except PabrikError:
            return None, "mati"
        if op is None or op.kredensial is None:
            return None, "salah"
        cocok = self._verifikator.cocok(password, op.kredensial)
        if not cocok:
            return None, "salah"
        if not op.aktif:
            return None, "nonaktif"
        return op, "ok"

    def login_password(self, username: str, password: str) -> HasilLogin:
        """Login username/password: lokal dulu (admin), lalu pabrik; salah satu cocok masuk."""
        username = (username or "").strip()
        if not username or len(username) > USERNAME_MAKS or len(password) > PANJANG_MAKS:
            return HasilLogin(False, None, "kredensial_salah")
        kolam = self._ambil_kolam()
        if kolam is None:
            return HasilLogin(False, None, "audit_tidak_tersedia")
        pabrik = self._ambil_pabrik()
        try:
            sisa = self._status_kunci(kolam, username)
            if sisa is not None:
                self._audit(
                    kolam, username=username, sumber="lokal", hasil="gagal", alasan="terkunci"
                )
                logger.warning("login_ditolak_terkunci", extra={"username": username})
                return HasilLogin(False, None, "terkunci", sisa)

            lokal_cocok, lokal_ada = self._coba_lokal(kolam, username, password)
            if lokal_cocok:
                pengguna = Pengguna(username, None, Peran.ADMIN, "lokal", "password")
                self._audit(
                    kolam,
                    username=username,
                    sumber="lokal",
                    hasil="sukses",
                    peran=pengguna.peran.value,
                    detail={"via": "password"},
                )
                return HasilLogin(True, pengguna, "ok")

            if pabrik is None:
                op, status = None, "salah"
            else:
                op, status = self._coba_pabrik(pabrik, username, password)
            if op is not None:
                pengguna = Pengguna(
                    op.username, op.nama, peran_dari_pabrik(op.peran), "pabrik", "password"
                )
                self._audit(
                    kolam,
                    username=username,
                    sumber="pabrik",
                    hasil="sukses",
                    peran=pengguna.peran.value,
                    detail={"via": "password"},
                )
                return HasilLogin(True, pengguna, "ok")

            mati = status == "mati"
            # Bila akun lokal ada, kegagalan tetap dihitung (cegah tebak password saat pabrik mati).
            alasan_audit = "pabrik_tidak_tersedia" if mati and not lokal_ada else "kredensial_salah"
            self._audit(
                kolam,
                username=username,
                sumber="pabrik" if pabrik is not None else "lokal",
                hasil="gagal",
                alasan=alasan_audit,
                detail={"status_pabrik": status},
            )
            return HasilLogin(False, None, "pabrik_tidak_tersedia" if mati else "kredensial_salah")
        except _AuditGagal:
            return HasilLogin(False, None, "audit_tidak_tersedia")
        except psycopg.Error:
            logger.exception("login_db_galat")
            return HasilLogin(False, None, "audit_tidak_tersedia")

    def login_rfid(self, uid: str) -> HasilLogin:
        """Login RFID (hanya pabrik, selalu operator); UID mentah tidak dicatat."""
        uid = (uid or "").strip()
        kolam = self._ambil_kolam()
        pabrik = self._ambil_pabrik()
        if kolam is None:
            return HasilLogin(False, None, "audit_tidak_tersedia")
        if pabrik is None or not uid:
            return HasilLogin(
                False, None, "pabrik_tidak_tersedia" if pabrik is None else "tidak_dikenal"
            )
        jejak = {"via": "rfid", "uid_sha256": hashlib.sha256(uid.encode()).hexdigest()[:8]}
        try:
            try:
                op = pabrik.ambil_operator(rfid=uid)
            except PabrikError:
                self._audit(
                    kolam,
                    username=None,
                    sumber="pabrik",
                    hasil="gagal",
                    alasan="pabrik_tidak_tersedia",
                    detail=jejak,
                )
                return HasilLogin(False, None, "pabrik_tidak_tersedia")
            if op is None or not op.aktif:
                self._audit(
                    kolam,
                    username=op.username if op else None,
                    sumber="pabrik",
                    hasil="gagal",
                    alasan="tidak_dikenal",
                    detail=jejak,
                )
                return HasilLogin(False, None, "tidak_dikenal")
            pengguna = Pengguna(op.username, op.nama, Peran.OPERATOR, "pabrik", "rfid")
            self._audit(
                kolam,
                username=op.username,
                sumber="pabrik",
                hasil="sukses",
                peran=Peran.OPERATOR.value,
                detail=jejak,
            )
            return HasilLogin(True, pengguna, "ok")
        except _AuditGagal:
            return HasilLogin(False, None, "audit_tidak_tersedia")
        except psycopg.Error:
            logger.exception("login_db_galat")
            return HasilLogin(False, None, "audit_tidak_tersedia")
