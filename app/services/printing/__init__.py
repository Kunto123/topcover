"""Antarmuka printer `PrintPort`, adapter simulasi, dan gerbang print."""

from app.core.config import Settings
from app.services.printing.dryrun import PrintDryRun
from app.services.printing.gerbang import cetak_jika_boleh
from app.services.printing.port import (
    HasilGerbang,
    HasilPrint,
    KeputusanPrint,
    PrintJob,
    PrintPort,
)

__all__ = [
    "HasilGerbang",
    "HasilPrint",
    "KeputusanPrint",
    "PrintDryRun",
    "PrintJob",
    "PrintPort",
    "buat_print_port",
    "cetak_jika_boleh",
]


def buat_print_port(settings: Settings) -> PrintPort:
    """Bangun printer sesuai `settings.printer_mode`; mode tak dikenal -> ValueError."""
    if settings.printer_mode == "dryrun":
        return PrintDryRun()
    raise ValueError(f"printer_mode tidak dikenal: {settings.printer_mode!r}")
