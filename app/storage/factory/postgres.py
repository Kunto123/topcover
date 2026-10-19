"""Adapter database pabrik berbasis PostgreSQL: TLS terverifikasi, hak minimal, waktu tulis pendek.

Nilai data TIDAK PERNAH masuk ke log atau pesan galat; hanya kelas galat dan `sqlstate`.
"""

import logging
import math
from typing import Any

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.errors import LockNotAvailable, QueryCanceled
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool, PoolTimeout

from app.storage.factory.pemetaan import PemetaanPabrik
from app.storage.factory.port import (
    OperatorPabrik,
    PabrikError,
    PabrikTidakTersedia,
    PushGagal,
    PushTimeout,
)
from app.storage.local.db import ringkas_target
from app.storage.local.skema import RekamanHasil

logger = logging.getLogger("app.storage.factory.postgres")

HOST_LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1", ""})
SSLMODE_AMAN = frozenset({"verify-full", "verify-ca"})


class KonfigTLSTidakAman(ValueError):
    """DSN pabrik ke host non-loopback tidak memakai TLS terverifikasi; pesan tanpa password."""


def validasi_tls(dsn: str) -> None:
    """Wajibkan `sslmode=verify-full|verify-ca` + `sslrootcert` untuk host selain loopback."""
    info = conninfo_to_dict(dsn)
    hosts = [h.strip() for h in (info.get("host") or "").split(",")]
    remote = [h for h in hosts if h not in HOST_LOOPBACK]
    if not remote:
        return
    mode = info.get("sslmode")
    if mode not in SSLMODE_AMAN:
        raise KonfigTLSTidakAman(
            f"Koneksi ke pabrik {', '.join(remote)} wajib sslmode=verify-full atau verify-ca "
            f"(dapat: {mode or 'tidak diset'})."
        )
    if not info.get("sslrootcert"):
        raise KonfigTLSTidakAman(
            f"Koneksi ke pabrik {', '.join(remote)} wajib menyertakan sslrootcert."
        )


def _ms(detik: float) -> int:
    """Ubah detik menjadi milidetik bulat (minimal 1)."""
    return max(1, math.ceil(detik * 1000))


class PabrikPostgres:
    """Memenuhi `PortPabrik` untuk PostgreSQL pabrik sesuai `pemetaan`."""

    def __init__(
        self,
        dsn: str,
        pemetaan: PemetaanPabrik,
        *,
        connect_timeout_s: float,
        write_timeout_s: float,
    ) -> None:
        """Siapkan kolam (belum dibuka); `connect_timeout_s`/`write_timeout_s` batas waktu detik."""
        self._dsn = dsn
        self._peta = pemetaan
        self._connect_s = connect_timeout_s
        self._target = ringkas_target(dsn)
        ms = _ms(write_timeout_s)
        self._kolam: ConnectionPool = ConnectionPool(
            conninfo=dsn,
            min_size=1,
            max_size=2,
            open=False,
            check=ConnectionPool.check_connection,
            kwargs={
                "row_factory": dict_row,
                "connect_timeout": math.ceil(connect_timeout_s),
                "application_name": "casing-edge",
                "options": (
                    f"-c statement_timeout={ms} -c lock_timeout=1000"
                    f" -c idle_in_transaction_session_timeout={ms * 2}"
                ),
                "tcp_user_timeout": ms,
            },
        )

    def buka(self, *, tunggu: bool = True) -> None:
        """Validasi TLS lalu buka kolam; `tunggu=False` tidak gagal bila server belum terjangkau."""
        validasi_tls(self._dsn)
        try:
            self._kolam.open(wait=tunggu, timeout=self._connect_s + 1)
        except PoolTimeout as exc:
            self._kolam.close()
            raise PabrikTidakTersedia(f"Pabrik {self._target} tidak terjangkau.") from exc

    def push_hasil(self, rekaman: RekamanHasil) -> None:
        """INSERT satu hasil sesuai pemetaan; gagal -> PushGagal/PushTimeout tanpa nilai data."""
        t = self._peta.hasil
        nilai: dict[str, Any] = {
            "cycle_id": rekaman.cycle_id,
            "datapart": rekaman.datapart,
            "verdict": t.nilai_verdict[rekaman.verdict.value],  # type: ignore[index]
            "reason_code": rekaman.reason_code.value if rekaman.reason_code else None,
            "operator": rekaman.operator,
            "waktu_scan": rekaman.waktu_scan,
            "durasi_total_ms": rekaman.durasi_total_ms,
            "path_gambar": rekaman.path_gambar,
        }
        kolom: list[sql.Composable] = []
        isi: list[sql.Composable] = []
        params: list[Any] = []
        for logis, tujuan in t.kolom.items():
            kolom.append(sql.Identifier(tujuan))
            if logis == "waktu_simpan":
                isi.append(sql.SQL("now()"))
            else:
                isi.append(sql.Placeholder())
                params.append(nilai[logis])
        for tujuan, konstanta in t.nilai_tetap.items():
            kolom.append(sql.Identifier(tujuan))
            isi.append(sql.Placeholder())
            params.append(konstanta)
        query = sql.SQL("INSERT INTO {tabel} ({kolom}) VALUES ({isi})").format(
            tabel=sql.Identifier(t.skema, t.nama),
            kolom=sql.SQL(", ").join(kolom),
            isi=sql.SQL(", ").join(isi),
        )
        try:
            with self._kolam.connection(timeout=self._connect_s) as conn:
                conn.execute(query, params)
        except PoolTimeout as exc:
            raise PushTimeout(f"Pabrik {self._target}: tidak bisa terhubung tepat waktu.") from exc
        except (QueryCanceled, LockNotAvailable) as exc:
            raise PushTimeout(
                f"Pabrik {self._target}: tulis melewati batas waktu ({exc.sqlstate})."
            ) from exc
        except (psycopg.OperationalError, psycopg.InterfaceError) as exc:
            # Bila putus tepat saat COMMIT, hasil mungkin sudah masuk (status tidak pasti).
            logger.warning("push_status_tidak_pasti", extra={"galat": type(exc).__name__})
            raise PushGagal(
                f"Pabrik {self._target}: koneksi gagal ({type(exc).__name__})."
            ) from exc
        except psycopg.Error as exc:
            raise PushGagal(
                f"Pabrik {self._target}: tulis ditolak ({type(exc).__name__}, {exc.sqlstate})."
            ) from exc

    def ambil_operator(
        self, *, username: str | None = None, rfid: str | None = None
    ) -> OperatorPabrik | None:
        """Cari operator di tabel pabrik by username atau rfid (tepat satu)."""
        if (username is None) == (rfid is None):
            raise ValueError("isi tepat satu dari username atau rfid")
        peta = self._peta.operator
        if peta is None:
            raise PabrikTidakTersedia("Tabel operator pabrik belum dipetakan.")
        kunci = "username" if username is not None else "rfid"
        if kunci not in peta.kolom:
            raise PabrikTidakTersedia(f"Kolom {kunci} operator belum dipetakan.")
        pilih = sql.SQL(", ").join(
            sql.SQL("{} AS {}").format(sql.Identifier(tujuan), sql.Identifier(logis))
            for logis, tujuan in peta.kolom.items()
        )
        query = sql.SQL("SELECT {pilih} FROM {tabel} WHERE {kunci} = %s LIMIT 1").format(
            pilih=pilih,
            tabel=sql.Identifier(peta.skema, peta.nama),
            kunci=sql.Identifier(peta.kolom[kunci]),  # type: ignore[index]
        )
        try:
            with self._kolam.connection(timeout=self._connect_s) as conn:
                baris = conn.execute(query, [username if username is not None else rfid]).fetchone()
        except (PoolTimeout, psycopg.Error) as exc:
            raise PabrikTidakTersedia(
                f"Pabrik {self._target}: baca operator gagal ({type(exc).__name__})."
            ) from exc
        if baris is None:
            return None
        diterima = {str(v).strip().lower() for v in peta.nilai_aktif}
        aktif = str(baris["aktif"]).strip().lower() in diterima
        peran = baris.get("peran")
        nama = baris.get("nama")
        kredensial = baris.get("kredensial")
        return OperatorPabrik(
            username=str(baris["username"]),
            nama=None if nama is None else str(nama),
            peran=None if peran is None else str(peran),
            aktif=aktif,
            kredensial=None if kredensial is None else str(kredensial),
        )

    def ping(self) -> None:
        """`SELECT 1`; gagal -> PabrikTidakTersedia."""
        try:
            with self._kolam.connection(timeout=self._connect_s) as conn:
                conn.execute("SELECT 1")
        except (PoolTimeout, psycopg.Error) as exc:
            raise PabrikTidakTersedia(f"Pabrik {self._target}: ping gagal.") from exc

    def tutup(self) -> None:
        """Tutup kolam (idempoten)."""
        self._kolam.close()


__all__ = ["KonfigTLSTidakAman", "PabrikError", "PabrikPostgres", "validasi_tls"]
