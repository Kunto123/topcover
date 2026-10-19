"""Adapter printer simulasi: mencatat perintah cetak tanpa mencetak label fisik."""

import logging
import threading
from collections import deque

from app.core.logging import bind_cycle_id
from app.services.printing.port import HasilPrint, PrintJob

logger = logging.getLogger("app.printing.dryrun")


class PrintDryRun:
    """Printer simulasi: log + riwayat memori; aman dipakai sebelum printer asli ada."""

    nama = "dryrun"

    def __init__(self, riwayat_maks: int = 100) -> None:
        """`riwayat_maks` = jumlah job terakhir yang disimpan di memori."""
        self._riwayat: deque[PrintJob] = deque(maxlen=riwayat_maks)
        self._lock = threading.Lock()
        self._jumlah = 0

    def cetak(self, job: PrintJob) -> HasilPrint:
        """Catat `job` (log + riwayat) dan kembalikan hasil yang jelas bertanda DRY-RUN."""
        with self._lock:
            self._jumlah += 1
            nomor = self._jumlah
            self._riwayat.append(job)
        with bind_cycle_id(job.cycle_id):
            logger.info(
                "print_dryrun",
                extra={"datapart_kode": job.datapart_kode, "nomor": nomor},
            )
        return HasilPrint(True, "DRY-RUN: tidak ada label fisik dicetak", f"dryrun-{nomor}")

    def riwayat(self) -> list[PrintJob]:
        """Salinan job terakhir (paling lama dulu), terbatas `riwayat_maks`."""
        with self._lock:
            return list(self._riwayat)

    @property
    def jumlah_dicetak(self) -> int:
        """Total perintah cetak sejak dibuat (tidak terbatas `riwayat_maks`)."""
        with self._lock:
            return self._jumlah
