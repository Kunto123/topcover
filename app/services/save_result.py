"""Simpan hasil siklus secara atomik: transaksi lokal -> push pabrik -> commit lokal (CV-4).

Hasil hanya ada di lokal bila push ke pabrik berhasil (data lokal = data yang terkirim).
"""

import logging
import time
from dataclasses import dataclass

from psycopg_pool import ConnectionPool

from app.core.logging import bind_cycle_id
from app.core.reasons import ReasonCode
from app.storage.factory.port import PabrikError, PortPabrik, PushTimeout
from app.storage.local import hasil
from app.storage.local.skema import RekamanHasil

logger = logging.getLogger("app.save_result")

WAKTU_AMBIL_KONEKSI_DETIK = 2
ULANG_LOKAL_MAKS = 2


class SimpanGagal(RuntimeError):
    """Akar semua kegagalan simpan; `reason_code` diisi bila ada kode alasan sistem."""

    reason_code: ReasonCode | None = None


class PabrikTidakDikonfigurasi(SimpanGagal):
    """Database pabrik tidak dikonfigurasi (`factory_mode=nonaktif`); tidak ada yang tertulis."""


class SimpanLokalGagal(SimpanGagal):
    """Simpan lokal gagal SEBELUM push; pabrik tidak terisi."""


class GagalPush(SimpanGagal):
    """Push ke pabrik gagal; lokal di-rollback. Operator harus mengulang siklus."""

    reason_code = ReasonCode.GAGAL_PUSH


class LokalGagalSetelahPush(SimpanGagal):
    """Pabrik sudah terisi tetapi lokal gagal commit (setelah diulang); rekonsiliasi manual."""


@dataclass(frozen=True, slots=True)
class HasilSimpan:
    """Hasil simpan: `rekaman_id` lokal dan `tahap_ms` (simpan_lokal, push_pabrik, commit)."""

    rekaman_id: int
    tahap_ms: dict[str, int]


def _ms(mulai: float) -> int:
    """Milidetik sejak `mulai` (perf_counter)."""
    return int((time.perf_counter() - mulai) * 1000)


def _ulangi_lokal(kolam: ConnectionPool, rekaman: RekamanHasil) -> int:
    """Ulangi simpan lokal (idempoten lewat cycle_id UNIQUE); kembalikan id atau lempar galat."""
    galat: Exception | None = None
    for _ in range(ULANG_LOKAL_MAKS):
        try:
            with kolam.connection(timeout=WAKTU_AMBIL_KONEKSI_DETIK) as conn:
                with conn.transaction():
                    return hasil.simpan(conn, rekaman)
        except hasil.CycleIdSudahAda:
            # Commit pertama ternyata berhasil (hanya ACK yang hilang): baris sudah ada.
            with kolam.connection(timeout=WAKTU_AMBIL_KONEKSI_DETIK) as conn:
                baris = hasil.ambil_by_cycle_id(conn, rekaman.cycle_id)
            if baris is not None:
                return int(baris["id"])
        except Exception as exc:
            galat = exc
    raise LokalGagalSetelahPush(
        "Hasil sudah tersimpan di pabrik tetapi gagal disimpan lokal "
        f"({type(galat).__name__ if galat else 'tak diketahui'}); hubungi SPV."
    ) from galat


def simpan_hasil(
    kolam: ConnectionPool | None, pabrik: PortPabrik | None, rekaman: RekamanHasil
) -> HasilSimpan:
    """Simpan `rekaman` ke lokal dan pabrik secara atomik; sinkron (panggil lewat thread).

    Galat: PabrikTidakDikonfigurasi, SimpanLokalGagal, GagalPush, LokalGagalSetelahPush.
    """
    with bind_cycle_id(rekaman.cycle_id):
        if pabrik is None:
            raise PabrikTidakDikonfigurasi(
                "Database pabrik tidak dikonfigurasi; hasil tidak disimpan."
            )
        if kolam is None:
            raise SimpanLokalGagal("Database lokal tidak tersedia; hasil tidak disimpan.")

        tahap: dict[str, int] = {}
        sudah_push = False
        id_lokal: int | None = None
        try:
            with kolam.connection(timeout=WAKTU_AMBIL_KONEKSI_DETIK) as conn:
                with conn.transaction():
                    t0 = time.perf_counter()
                    try:
                        id_lokal = hasil.simpan(conn, rekaman)
                    except Exception as exc:
                        raise SimpanLokalGagal(
                            f"Simpan lokal gagal ({type(exc).__name__}): {exc}"
                        ) from exc
                    tahap["simpan_lokal"] = _ms(t0)

                    t1 = time.perf_counter()
                    try:
                        pabrik.push_hasil(rekaman)
                    except PabrikError as exc:
                        tahap["push_pabrik"] = _ms(t1)
                        logger.warning(
                            "push_gagal",
                            extra={
                                "galat": type(exc).__name__,
                                "timeout": isinstance(exc, PushTimeout),
                                "tahap_ms": tahap,
                            },
                        )
                        raise GagalPush(f"Push ke pabrik gagal: {exc}") from exc
                    tahap["push_pabrik"] = _ms(t1)
                    sudah_push = True
                    t2 = time.perf_counter()
                # transaksi di-commit saat keluar blok `transaction()`
                tahap["commit"] = _ms(t2)
        except SimpanGagal:
            raise
        except Exception as exc:
            if not sudah_push:
                raise SimpanLokalGagal(f"Simpan lokal gagal ({type(exc).__name__}).") from exc
            logger.error(
                "commit_lokal_gagal_setelah_push",
                extra={"galat": type(exc).__name__},
            )
            try:
                id_lokal = _ulangi_lokal(kolam, rekaman)
            except LokalGagalSetelahPush:
                logger.error(
                    "lokal_gagal_setelah_push",
                    extra={
                        "datapart": rekaman.datapart,
                        "verdict": rekaman.verdict.value,
                        "operator": rekaman.operator,
                    },
                )
                raise

        assert id_lokal is not None
        logger.info("hasil_disimpan", extra={"rekaman_id": id_lokal, "tahap_ms": tahap})
        return HasilSimpan(id_lokal, tahap)
