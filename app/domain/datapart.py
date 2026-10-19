"""Parser datapart. FORMAT FINAL TBD (menunggu pemilik produk); saat ini hanya `ParserStub`."""

import re
from typing import Protocol

from app.domain.types import Datapart, PartKelas

_VARIAN = re.compile(r"[A-Za-z0-9_]+")


class DatapartTidakValid(ValueError):
    """Kode datapart tidak bisa diurai; pesan menyebut bagian yang salah."""


class DatapartParser(Protocol):
    """Antarmuka parser datapart; implementasi final diganti lewat `app.state.parser`."""

    def urai(self, kode: str) -> Datapart:
        """Urai `kode` mentah menjadi Datapart atau lempar DatapartTidakValid."""
        ...


class ParserStub:
    """Parser SEMENTARA: format `TIPE-VARIAN[-JUMLAH]`, mis. `KIRI-MERAH-6` atau `kanan-hitam`.

    Format final belum ditetapkan pemilik produk; jangan dipakai sebagai spesifikasi.
    """

    def urai(self, kode: str) -> Datapart:
        """Urai `kode` (tidak peka huruf besar); `Datapart.kode` menyimpan kode mentah."""
        bagian = kode.strip().split("-")
        if len(bagian) not in (2, 3):
            raise DatapartTidakValid(
                f"format datapart harus TIPE-VARIAN[-JUMLAH], dapat {len(bagian)} bagian"
            )
        tipe_teks, varian = bagian[0].strip().lower(), bagian[1].strip()
        if tipe_teks not in {k.value for k in PartKelas}:
            raise DatapartTidakValid(f"tipe {bagian[0]!r} tidak dikenal; harus KIRI atau KANAN")
        if not _VARIAN.fullmatch(varian):
            raise DatapartTidakValid(f"varian warna {bagian[1]!r} tidak valid")
        jumlah = None
        if len(bagian) == 3:
            teks = bagian[2].strip()
            if not teks.isdigit() or not 1 <= int(teks) <= 6:
                raise DatapartTidakValid(f"jumlah {bagian[2]!r} harus angka 1-6")
            jumlah = int(teks)
        return Datapart(
            kode=kode, tipe=PartKelas(tipe_teks), varian_warna=varian.lower(), jumlah_isi=jumlah
        )
