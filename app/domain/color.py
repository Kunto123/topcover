"""Pengukuran warna part dari gambar + mask, dalam ruang warna yang bisa diganti.

Fungsi murni: tanpa I/O, tanpa log. Median dipakai (bukan rata-rata) agar tahan highlight plastik.
"""

import math
from typing import Protocol

import cv2
import numpy as np

Warna = tuple[float, float, float]

PERIODE_HUE = 180.0  # OpenCV: H dalam [0, 180)
SKALA_HUE = 255.0 / PERIODE_HUE  # menyamakan skala hue dengan S dan V (0-255)


class RuangWarna(Protocol):
    """Kontrak ruang warna: konversi piksel BGR dan jarak antar dua warna."""

    nama: str

    def dari_bgr(self, bgr_uint8: np.ndarray) -> np.ndarray:
        """Ubah piksel BGR uint8 bentuk (N,3) menjadi float64 (N,3) di ruang ini."""
        ...

    def jarak(self, a: Warna, b: Warna) -> float:
        """Jarak antara dua warna di ruang ini (>= 0, simetris)."""
        ...


def _euclid(a: Warna, b: Warna) -> float:
    """Jarak Euclid tiga kanal."""
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b, strict=True)))


class _Lab:
    """CIELAB (jarak = CIE76 delta E); paling mendekati persepsi manusia."""

    nama = "lab"

    def dari_bgr(self, bgr_uint8: np.ndarray) -> np.ndarray:
        """Konversi lewat float32 0-1 agar L di [0,100] dan a,b di [-127,127]."""
        skala = (bgr_uint8.astype(np.float32) / 255.0).reshape(-1, 1, 3)
        return cv2.cvtColor(skala, cv2.COLOR_BGR2Lab).reshape(-1, 3).astype(np.float64)

    def jarak(self, a: Warna, b: Warna) -> float:
        """Delta E CIE76 (jarak Euclid di Lab)."""
        return _euclid(a, b)


class _YCrCb:
    """YCrCb 8-bit (0-255); kandidat pemisah luma dan chroma."""

    nama = "ycrcb"

    def dari_bgr(self, bgr_uint8: np.ndarray) -> np.ndarray:
        """Konversi uint8 ke YCrCb lalu ke float64."""
        piksel = bgr_uint8.astype(np.uint8).reshape(-1, 1, 3)
        return cv2.cvtColor(piksel, cv2.COLOR_BGR2YCrCb).reshape(-1, 3).astype(np.float64)

    def jarak(self, a: Warna, b: Warna) -> float:
        """Jarak Euclid di YCrCb."""
        return _euclid(a, b)


class _Hsv:
    """HSV 8-bit (H 0-179, S,V 0-255); hue melingkar. Bobot hue perkiraan, CV-S1 yang memutuskan."""

    nama = "hsv"

    def dari_bgr(self, bgr_uint8: np.ndarray) -> np.ndarray:
        """Konversi uint8 ke HSV lalu ke float64."""
        piksel = bgr_uint8.astype(np.uint8).reshape(-1, 1, 3)
        return cv2.cvtColor(piksel, cv2.COLOR_BGR2HSV).reshape(-1, 3).astype(np.float64)

    def jarak(self, a: Warna, b: Warna) -> float:
        """Jarak dengan selisih hue melingkar (periode 180) diskalakan ke 0-255."""
        dh = abs(a[0] - b[0])
        dh = min(dh, PERIODE_HUE - dh) * SKALA_HUE
        return math.sqrt(dh**2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


RUANG_WARNA: dict[str, RuangWarna] = {"lab": _Lab(), "ycrcb": _YCrCb(), "hsv": _Hsv()}


def ambil_ruang(nama: str) -> RuangWarna:
    """Ambil ruang warna terdaftar; `nama` tak dikenal -> ValueError berpesan daftar yang ada."""
    try:
        return RUANG_WARNA[nama]
    except KeyError:
        raise ValueError(
            f"ruang warna {nama!r} tidak dikenal; pilih salah satu: {sorted(RUANG_WARNA)}"
        ) from None


def jarak_warna(ruang: str, a: Warna, b: Warna) -> float:
    """Jarak antara warna `a` dan `b` di ruang bernama `ruang`."""
    return ambil_ruang(ruang).jarak(a, b)


def ukur_warna(
    gambar_bgr: np.ndarray,
    mask: np.ndarray,
    ruang: str = "lab",
    *,
    erosi_px: int = 3,
    min_piksel: int = 500,
    buang_atas_persentil: float = 5.0,
    ambang_putih: int = 240,
) -> Warna | None:
    """Median warna `gambar_bgr` di dalam `mask`, atau None bila piksel kurang dari `min_piksel`.

    `erosi_px` mengikis tepi; `buang_atas_persentil` dan `ambang_putih` membuang highlight.
    """
    if gambar_bgr.dtype != np.uint8 or gambar_bgr.ndim != 3 or gambar_bgr.shape[2] != 3:
        raise ValueError("gambar_bgr harus uint8 berbentuk (H, W, 3)")
    if mask.ndim != 2 or mask.shape != gambar_bgr.shape[:2]:
        raise ValueError(
            f"ukuran mask {mask.shape} tidak sama dengan gambar {gambar_bgr.shape[:2]}"
        )
    if mask.dtype not in (np.bool_, np.uint8):
        raise ValueError("mask harus bool atau uint8")
    ruang_obj = ambil_ruang(ruang)

    mask_u8 = (mask > 0).astype(np.uint8)
    if erosi_px > 0:
        ukuran = 2 * erosi_px + 1
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ukuran, ukuran))
        mask_u8 = cv2.erode(mask_u8, kernel)

    piksel = gambar_bgr[mask_u8 > 0]
    if piksel.shape[0] == 0:
        return None
    piksel = piksel[piksel.min(axis=1) < ambang_putih]
    if piksel.shape[0] == 0:
        return None
    abu = piksel.astype(np.float64).mean(axis=1)
    batas = np.percentile(abu, 100.0 - buang_atas_persentil)
    piksel = piksel[abu <= batas]
    if piksel.shape[0] < min_piksel:
        return None

    median = np.median(ruang_obj.dari_bgr(piksel), axis=0)
    return (float(median[0]), float(median[1]), float(median[2]))
