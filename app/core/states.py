"""State siklus verifikasi satu box; logika transisi dimiliki CV-6, bukan modul ini."""

from enum import StrEnum


class CycleState(StrEnum):
    """Urutan state siklus dari scan datapart sampai selesai print."""

    WAIT_DATAPART = "WAIT_DATAPART"
    READY = "READY"
    CAPTURING = "CAPTURING"
    INFERRING = "INFERRING"
    JUDGED = "JUDGED"
    SAVING = "SAVING"
    PRINTING = "PRINTING"
    DONE = "DONE"
