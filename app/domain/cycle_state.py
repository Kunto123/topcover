"""State machine siklus pemeriksaan satu box (thread-safe, tanpa logika kamera/inferensi).

Urutan baku: WAIT_DATAPART -> READY -> CAPTURING -> INFERRING -> JUDGED -> SAVING ->
PRINTING -> DONE. NOT_MATCH berakhir di SAVING -> DONE. Setiap transisi dicatat bersama `cycle_id`.
"""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.core.logging import bind_cycle_id, new_cycle_id
from app.core.reasons import ReasonCode
from app.core.states import CycleState
from app.domain.types import Datapart

logger = logging.getLogger("app.domain.cycle")

S = CycleState
TRANSISI: dict[CycleState, frozenset[CycleState]] = {
    S.WAIT_DATAPART: frozenset({S.READY}),
    S.READY: frozenset({S.READY, S.CAPTURING}),  # READY->READY = scan ulang
    S.CAPTURING: frozenset({S.INFERRING}),
    S.INFERRING: frozenset({S.JUDGED}),
    S.JUDGED: frozenset({S.SAVING}),
    S.SAVING: frozenset({S.PRINTING, S.DONE}),  # DONE langsung untuk NOT_MATCH
    S.PRINTING: frozenset({S.DONE}),
    S.DONE: frozenset({S.WAIT_DATAPART}),
}


class TransisiTidakValid(RuntimeError):
    """Transisi state siklus yang tidak diizinkan oleh tabel `TRANSISI`."""


@dataclass(frozen=True, slots=True)
class Peristiwa:
    """Satu transisi: dari/ke state, `cycle_id`, kode datapart, waktu monotonik, dan alasan."""

    dari: CycleState
    ke: CycleState
    cycle_id: str | None
    datapart_kode: str | None
    waktu_monotonik: float
    alasan: str | None


class MesinSiklus:
    """Mesin state siklus. Semua mutasi dilindungi RLock; pendengar dipanggil setelah lock lepas."""

    def __init__(self, jam: Callable[[], float] = time.monotonic) -> None:
        """`jam` = sumber waktu monotonik (bisa diganti di test)."""
        self._lock = threading.RLock()
        self._jam = jam
        self._pendengar: list[Callable[[Peristiwa], None]] = []
        self.state: CycleState = CycleState.WAIT_DATAPART
        self.cycle_id: str | None = None
        self.datapart: Datapart | None = None
        self._jejak: list[tuple[CycleState, float]] = []

    @property
    def waktu_masuk(self) -> dict[CycleState, float]:
        """Waktu monotonik masuk tiap state pada siklus berjalan."""
        with self._lock:
            return dict(self._jejak)

    def umur_state(self, state: CycleState) -> float | None:
        """Detik sejak siklus ini masuk `state` (jam yang sama dengan mesin), atau None."""
        with self._lock:
            for s, masuk in self._jejak:
                if s is state:
                    return self._jam() - masuk
        return None

    def tambah_pendengar(self, fn: Callable[[Peristiwa], None]) -> None:
        """Daftarkan `fn(Peristiwa)`; exception di dalamnya dicatat, transisi tetap berlaku."""
        with self._lock:
            self._pendengar.append(fn)

    def terima_datapart(self, datapart: Datapart) -> str:
        """Terima datapart (dari WAIT/READY/DONE), mulai siklus baru, kembalikan cycle_id."""
        with self._lock:
            if self.state not in (S.WAIT_DATAPART, S.READY, S.DONE):
                raise TransisiTidakValid(
                    f"datapart tidak bisa diterima saat state {self.state.value}"
                )
            ulang = self.state is S.READY
            alasan = "scan_ulang" if ulang else ("scan_baru" if self.state is S.DONE else None)
            peristiwa = self._terapkan(S.READY, alasan, datapart)
            pendengar = list(self._pendengar)
            cycle_id = self.cycle_id or ""
        self._beritahu(pendengar, peristiwa)
        return cycle_id

    def pindah(self, ke: CycleState, alasan: str | None = None) -> None:
        """Pindah ke state `ke` bila sah menurut `TRANSISI`; masuk READY lewat `terima_datapart`."""
        with self._lock:
            if ke is S.READY:
                raise TransisiTidakValid("masuk READY hanya lewat terima_datapart()")
            if ke not in TRANSISI[self.state]:
                raise TransisiTidakValid(
                    f"transisi {self.state.value} -> {ke.value} tidak diizinkan"
                )
            peristiwa = self._terapkan(ke, alasan, self.datapart)
            pendengar = list(self._pendengar)
        self._beritahu(pendengar, peristiwa)

    def batalkan(self, alasan: ReasonCode | str) -> None:
        """Kembali ke WAIT_DATAPART dari state mana pun dan kosongkan siklus (reset/gagal/error)."""
        teks = alasan.value if isinstance(alasan, ReasonCode) else alasan
        with self._lock:
            if self.state is S.WAIT_DATAPART and self.cycle_id is None:
                return
            peristiwa = self._terapkan(S.WAIT_DATAPART, teks, None)
            pendengar = list(self._pendengar)
        self._beritahu(pendengar, peristiwa)

    def reset(self) -> None:
        """Alias `batalkan` tanpa alasan khusus (dipakai setelah DONE)."""
        self.batalkan("reset")

    def ringkasan(self) -> dict[str, Any]:
        """Ringkasan state untuk UI/API: state, cycle_id, datapart, dan durasi (ms) per state."""
        with self._lock:
            sekarang = self._jam()
            durasi: dict[str, int] = {}
            for i, (state, masuk) in enumerate(self._jejak):
                akhir = self._jejak[i + 1][1] if i + 1 < len(self._jejak) else sekarang
                durasi[state.value] = durasi.get(state.value, 0) + int((akhir - masuk) * 1000)
            dp = self.datapart
            return {
                "state": self.state.value,
                "cycle_id": self.cycle_id,
                "datapart": None
                if dp is None
                else {
                    "kode": dp.kode,
                    "tipe": dp.tipe.value,
                    "varian_warna": dp.varian_warna,
                    "jumlah_isi": dp.jumlah_isi,
                },
                "durasi_ms": durasi,
            }

    def _terapkan(self, ke: CycleState, alasan: str | None, datapart: Datapart | None) -> Peristiwa:
        """Terapkan transisi di bawah lock, catat log, dan bangun Peristiwa. Lock harus dipegang."""
        dari = self.state
        cycle_lama = self.cycle_id
        sekarang = self._jam()
        if ke is S.READY:
            self.cycle_id = new_cycle_id()
            self.datapart = datapart
            self._jejak = []
        elif ke is S.WAIT_DATAPART:
            self.cycle_id = None
            self.datapart = None
            self._jejak = []
        self.state = ke
        self._jejak.append((ke, sekarang))
        pencatat_id = self.cycle_id or cycle_lama
        kode = self.datapart.kode if self.datapart else None
        pesan = "siklus_scan_ulang" if alasan == "scan_ulang" else "siklus_transisi"
        if pencatat_id:
            with bind_cycle_id(pencatat_id):
                logger.info(
                    pesan,
                    extra={
                        "dari": dari.value,
                        "ke": ke.value,
                        "datapart": kode,
                        "alasan": alasan,
                    },
                )
        else:
            logger.info(pesan, extra={"dari": dari.value, "ke": ke.value, "alasan": alasan})
        return Peristiwa(dari, ke, pencatat_id, kode, sekarang, alasan)

    @staticmethod
    def _beritahu(pendengar: list[Callable[[Peristiwa], None]], peristiwa: Peristiwa) -> None:
        """Panggil semua pendengar di luar lock; exception dicatat, bukan dilempar."""
        for fn in pendengar:
            try:
                fn(peristiwa)
            except Exception:
                logger.exception("pendengar_siklus_gagal")
