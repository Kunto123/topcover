"""Gerbang print: satu-satunya jalur resmi memanggil printer.

Print hanya terjadi bila verdict MATCH **dan** rekaman sudah tersimpan (`rekaman_id` valid).
"""

import logging

from app.core.logging import bind_cycle_id
from app.core.reasons import Verdict
from app.services.printing.port import (
    HasilGerbang,
    HasilPrint,
    KeputusanPrint,
    PrintJob,
    PrintPort,
)

logger = logging.getLogger("app.printing.gerbang")


def _catat(hasil: HasilGerbang, verdict: Verdict, rekaman_id: int | None) -> HasilGerbang:
    """Catat keputusan gerbang ke log lalu kembalikan `hasil` apa adanya."""
    logger.info(
        "print_keputusan",
        extra={
            "keputusan": hasil.keputusan.value,
            "verdict": verdict.value,
            "rekaman_id": rekaman_id,
        },
    )
    return hasil


def cetak_jika_boleh(
    *, verdict: Verdict, rekaman_id: int | None, job: PrintJob, port: PrintPort
) -> HasilGerbang:
    """Cetak `job` lewat `port` hanya jika `verdict` (enum Verdict) MATCH dan `rekaman_id` > 0."""
    # `rekaman_id` adalah id baris yang sudah tersimpan. Gerbang tidak menyimpan, tidak
    # mengulang, dan tidak melempar saat cetak gagal.
    if not isinstance(verdict, Verdict):
        raise TypeError(f"verdict harus Verdict, dapat: {type(verdict).__name__}")

    with bind_cycle_id(job.cycle_id):
        if verdict is not Verdict.MATCH:
            hasil = HasilGerbang(
                KeputusanPrint.DILEWATI_NOT_MATCH, None, "Box NOT_MATCH: tidak boleh dicetak."
            )
            return _catat(hasil, verdict, rekaman_id)

        if rekaman_id is None or rekaman_id <= 0:
            logger.warning("print_ditolak_belum_tersimpan", extra={"rekaman_id": rekaman_id})
            hasil = HasilGerbang(
                KeputusanPrint.DILEWATI_BELUM_TERSIMPAN,
                None,
                "Rekaman belum tersimpan: tidak boleh dicetak.",
            )
            return _catat(hasil, verdict, rekaman_id)

        try:
            hasil_print = port.cetak(job)
        except Exception as exc:
            logger.exception("print_gagal_tak_terduga")
            hasil = HasilGerbang(
                KeputusanPrint.GAGAL_CETAK,
                HasilPrint(False, f"{type(exc).__name__}: {exc}"),
                f"Printer error tak terduga ({type(exc).__name__}).",
            )
            return _catat(hasil, verdict, rekaman_id)

        if not hasil_print.berhasil:
            hasil = HasilGerbang(
                KeputusanPrint.GAGAL_CETAK,
                hasil_print,
                f"Printer menolak: {hasil_print.pesan or 'tanpa pesan'}",
            )
            return _catat(hasil, verdict, rekaman_id)

        hasil = HasilGerbang(KeputusanPrint.DICETAK, hasil_print, hasil_print.pesan or "Dicetak.")
        return _catat(hasil, verdict, rekaman_id)
