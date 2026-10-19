"""Tipe dan antarmuka printer: `PrintPort`, `PrintJob`, `HasilPrint`, `KeputusanPrint`."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class PrintJob:
    """Perintah cetak: `cycle_id` siklus, `datapart_kode` mentah, `waktu`, `payload` tambahan.

    Format `payload` final belum diketahui (menunggu engineering); jangan mengasumsikan kunci.
    """

    cycle_id: str
    datapart_kode: str
    waktu: datetime
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Tolak `cycle_id` atau `datapart_kode` kosong."""
        if not self.cycle_id.strip():
            raise ValueError("cycle_id tidak boleh kosong")
        if not self.datapart_kode.strip():
            raise ValueError("datapart_kode tidak boleh kosong")


@dataclass(frozen=True, slots=True)
class HasilPrint:
    """Hasil satu perintah cetak: `berhasil`, `pesan`, `id_pekerjaan` printer (None = tak ada)."""

    berhasil: bool
    pesan: str = ""
    id_pekerjaan: str | None = None


class PrintPort(Protocol):
    """Antarmuka printer (sinkron).

    Implementasi tidak melempar untuk kegagalan biasa; kembalikan `HasilPrint(berhasil=False)`.
    """

    nama: str

    def cetak(self, job: PrintJob) -> HasilPrint:
        """Kirim satu perintah cetak ke printer dan kembalikan hasilnya."""
        ...


class KeputusanPrint(StrEnum):
    """Keputusan gerbang print. Nilai stabil: dipakai di log dan UI."""

    DICETAK = "dicetak"
    DILEWATI_NOT_MATCH = "dilewati_not_match"
    DILEWATI_BELUM_TERSIMPAN = "dilewati_belum_tersimpan"
    GAGAL_CETAK = "gagal_cetak"


@dataclass(frozen=True, slots=True)
class HasilGerbang:
    """Hasil gerbang: `keputusan`, `hasil_print` dari printer (None bila dilewati), `pesan`."""

    keputusan: KeputusanPrint
    hasil_print: HasilPrint | None
    pesan: str
