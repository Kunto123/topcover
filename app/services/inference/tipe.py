"""Tipe hasil inferensi dan galatnya (CV-8)."""

from dataclasses import dataclass

import numpy as np

from app.domain.types import PartKelas


class ModelTidakSiap(RuntimeError):
    """Model belum dimuat atau pekerja inferensi sedang macet; siklus tidak boleh dimulai."""


class ModelGagalDimuat(RuntimeError):
    """Model tidak bisa dimuat (berkas hilang, bentuk tidak didukung, kelas tidak sesuai)."""


class InferensiGagal(RuntimeError):
    """Inferensi atau pasca-proses gagal untuk satu frame."""


class InferensiTimeout(InferensiGagal):
    """Inferensi melewati batas waktu."""


@dataclass(frozen=True, slots=True)
class DeteksiPart:
    """Satu part terdeteksi: `kelas`, `keyakinan` 0-1, `bbox` (x1,y1,x2,y2) dan `mask` bool.

    `mask` berukuran sama dengan frame (H, W) sehingga langsung bisa diberikan ke `ukur_warna`.
    """

    kelas: PartKelas
    keyakinan: float
    bbox: tuple[int, int, int, int]
    mask: np.ndarray


@dataclass(frozen=True, slots=True)
class HasilInferensi:
    """Hasil satu frame: `deteksi` (menurun), `tahap_ms`, `model_versi`, `ukuran_frame`."""

    deteksi: tuple[DeteksiPart, ...]
    tahap_ms: dict[str, float]
    model_versi: str
    ukuran_frame: tuple[int, int]
