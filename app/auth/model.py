"""Tipe auth: peran, pengguna yang sedang masuk, dan hasil percobaan login."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal


class Peran(StrEnum):
    """Peran pengguna: operator (siklus) atau admin (layar admin)."""

    OPERATOR = "operator"
    ADMIN = "admin"


@dataclass(frozen=True, slots=True)
class Pengguna:
    """Pengguna yang masuk: `sumber` akun (lokal/pabrik) dan `via` cara masuk."""

    username: str
    nama: str | None
    peran: Peran
    sumber: Literal["lokal", "pabrik"]
    via: Literal["password", "rfid"]

    @property
    def tampil(self) -> str:
        """Nama untuk ditampilkan (nama lengkap bila ada, selain itu username)."""
        return self.nama or self.username


AlasanLogin = Literal[
    "ok",
    "kredensial_salah",
    "tidak_dikenal",
    "terkunci",
    "pabrik_tidak_tersedia",
    "audit_tidak_tersedia",
]


@dataclass(frozen=True, slots=True)
class HasilLogin:
    """Hasil login: `sukses`, `pengguna`, `alasan`, dan `sisa_kunci_menit` bila terkunci."""

    sukses: bool
    pengguna: Pengguna | None
    alasan: AlasanLogin
    sisa_kunci_menit: int | None = None
