"""Tipe domain bersama (kontrak lintas tiket): kelas part dan datapart."""

from dataclasses import dataclass
from enum import StrEnum


class PartKelas(StrEnum):
    """Tipe fisik part: kiri atau kanan (satu-satunya kelas yang dideteksi model)."""

    KIRI = "kiri"
    KANAN = "kanan"


@dataclass(frozen=True, slots=True)
class Datapart:
    """Hasil urai datapart: `kode` mentah, `tipe`, `varian_warna`, `jumlah_isi` (None = tak ada)."""

    kode: str
    tipe: PartKelas
    varian_warna: str
    jumlah_isi: int | None = None

    def __post_init__(self) -> None:
        """Tolak `kode`/`varian_warna` kosong dan `jumlah_isi` kurang dari 1."""
        if not self.kode.strip():
            raise ValueError("kode datapart tidak boleh kosong")
        if not self.varian_warna.strip():
            raise ValueError("varian_warna tidak boleh kosong")
        if self.jumlah_isi is not None and self.jumlah_isi < 1:
            raise ValueError(f"jumlah_isi harus >= 1, dapat: {self.jumlah_isi}")
