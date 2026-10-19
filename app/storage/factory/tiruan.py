"""Pabrik tiruan in-memory untuk test dan `factory_mode="tiruan"` (sengaja dibuat sederhana)."""

import threading
import time

from app.storage.factory.port import OperatorPabrik
from app.storage.local.skema import RekamanHasil


class PabrikTiruan:
    """Memenuhi `PortPabrik`; thread-safe. Kegagalan disuntik lewat atribut publik."""

    def __init__(self) -> None:
        self._kunci = threading.Lock()
        self.hasil: list[RekamanHasil] = []
        self.jumlah_push = 0  # semua percobaan, termasuk yang gagal
        self.gagal_push: Exception | None = None  # dilempar tiap push sampai di-reset ke None
        self.tunda_push_s: float = 0.0
        self.gagal_baca: Exception | None = None  # dilempar oleh ambil_operator dan ping
        self._per_username: dict[str, OperatorPabrik] = {}
        self._per_rfid: dict[str, OperatorPabrik] = {}

    def tambah_operator(self, op: OperatorPabrik, rfid: str | None = None) -> None:
        """Daftarkan operator, dan opsional kode RFID miliknya."""
        with self._kunci:
            self._per_username[op.username] = op
            if rfid is not None:
                self._per_rfid[rfid] = op

    def push_hasil(self, rekaman: RekamanHasil) -> None:
        """Simpan hasil; bila `gagal_push` terisi, lempar dan jangan simpan."""
        with self._kunci:
            self.jumlah_push += 1
            gagal, tunda = self.gagal_push, self.tunda_push_s
        if tunda > 0:
            time.sleep(tunda)
        if gagal is not None:
            raise gagal
        with self._kunci:
            self.hasil.append(rekaman)

    def ambil_operator(
        self, *, username: str | None = None, rfid: str | None = None
    ) -> OperatorPabrik | None:
        """Cari operator by username atau rfid (tepat satu); tidak ketemu -> None."""
        if (username is None) == (rfid is None):
            raise ValueError("isi tepat satu dari username atau rfid")
        with self._kunci:
            gagal = self.gagal_baca
            if gagal is None:
                if username is not None:
                    return self._per_username.get(username)
                return self._per_rfid.get(rfid or "")
        raise gagal

    def ping(self) -> None:
        """Lempar `gagal_baca` bila terisi."""
        with self._kunci:
            gagal = self.gagal_baca
        if gagal is not None:
            raise gagal

    def tutup(self) -> None:
        """No-op."""
