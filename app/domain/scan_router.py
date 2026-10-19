"""Penentu arah masukan scanner: RFID, datapart, atau diabaikan karena sibuk."""

from enum import StrEnum

from app.core.states import CycleState


class ArahScan(StrEnum):
    """Ke mana sebuah scan diarahkan oleh server."""

    RFID = "rfid"
    DATAPART = "datapart"
    SIBUK = "sibuk"


def arahkan_scan(sudah_login: bool, state: CycleState) -> ArahScan:
    """Belum login -> RFID; siap menerima (termasuk DONE) -> DATAPART; selain itu SIBUK."""
    # DONE menerima datapart agar operator tidak menunggu reset antar box (puncak 150 box/jam).
    # Kolom yang sedang fokus (login manual) ditangani browser: scan-nya tidak dikirim.
    if not sudah_login:
        return ArahScan.RFID
    if state in (CycleState.WAIT_DATAPART, CycleState.READY, CycleState.DONE):
        return ArahScan.DATAPART
    return ArahScan.SIBUK
