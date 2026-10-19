"""Verifikasi kredensial yang tersimpan di pabrik. Skema hash pabrik: TBD (lihat docs/auth.md)."""

import logging
from typing import Protocol

from app.auth.hash import verifikasi_password

logger = logging.getLogger("app.auth.kredensial")


class VerifikatorKredensial(Protocol):
    """Membandingkan password yang diketik dengan nilai tersimpan di tabel operator pabrik."""

    def cocok(self, input_password: str, tersimpan: str) -> bool:
        """True bila `input_password` cocok dengan `tersimpan`."""
        ...


class VerifikatorSementara:
    """Hanya mendukung `scrypt$...`; skema lain ditolak (tidak pernah membandingkan teks polos)."""

    def cocok(self, input_password: str, tersimpan: str) -> bool:
        """Cocokkan bila `tersimpan` berformat scrypt; selain itu False + WARNING."""
        if tersimpan.startswith("scrypt$"):
            return verifikasi_password(input_password, tersimpan)
        logger.warning("skema_hash_pabrik_belum_didukung")
        return False
