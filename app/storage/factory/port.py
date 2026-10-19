"""Kontrak akses database pabrik: kirim hasil dan baca operator (CV-0b; adapter nyata di CV-4)."""

from dataclasses import dataclass, field
from typing import Protocol

from app.storage.local.skema import RekamanHasil


@dataclass(frozen=True, slots=True)
class OperatorPabrik:
    """Operator menurut database pabrik; `kredensial` tidak pernah tampil di repr/log."""

    username: str
    nama: str | None
    peran: str | None  # nilai mentah dari pabrik; None = tidak ada kolom peran
    aktif: bool
    kredensial: str | None = field(default=None, repr=False)  # hash/teks tersimpan; JANGAN di-log


class PabrikError(RuntimeError):
    """Akar semua galat database pabrik."""


class PabrikTidakTersedia(PabrikError):
    """Koneksi atau pembacaan ke pabrik gagal atau melewati batas waktu."""


class PushGagal(PabrikError):
    """Penulisan hasil ke pabrik gagal."""


class PushTimeout(PushGagal):
    """Penulisan hasil ke pabrik melewati batas waktu."""


class PortPabrik(Protocol):
    """Antarmuka database pabrik. Semua method sinkron/blocking: panggil lewat thread."""

    def push_hasil(self, rekaman: RekamanHasil) -> None:
        """Tulis satu hasil; lempar PushGagal/PushTimeout bila gagal."""
        ...

    def ambil_operator(
        self, *, username: str | None = None, rfid: str | None = None
    ) -> OperatorPabrik | None:
        """Cari operator; wajib tepat satu dari `username`/`rfid` (selain itu ValueError)."""
        ...

    def ping(self) -> None:
        """Periksa koneksi; lempar PabrikTidakTersedia bila gagal."""
        ...

    def tutup(self) -> None:
        """Lepas koneksi (idempoten)."""
        ...
