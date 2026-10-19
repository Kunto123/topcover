"""Praproses frame untuk YOLO11: letterbox (rasio terjaga, pad abu 114) dan tensor NCHW."""

from dataclasses import dataclass

import cv2
import numpy as np

WARNA_PAD = 114


@dataclass(frozen=True, slots=True)
class Letterbox:
    """Parameter letterbox: `skala`, pad kiri/atas, ukuran gambar hasil resize, dan ukuran input."""

    skala: float
    kiri: int
    atas: int
    lebar: int
    tinggi: int
    input_w: int
    input_h: int


def letterbox(frame_bgr: np.ndarray, ukuran: tuple[int, int]) -> tuple[np.ndarray, Letterbox]:
    """Skalakan `frame_bgr` ke `ukuran` (tinggi, lebar) tanpa mengubah rasio; sisa diisi abu."""
    if frame_bgr.dtype != np.uint8 or frame_bgr.ndim != 3 or frame_bgr.shape[2] != 3:
        raise ValueError("frame harus uint8 berbentuk (H, W, 3)")
    ih, iw = ukuran
    h, w = frame_bgr.shape[:2]
    skala = min(ih / h, iw / w)
    lebar, tinggi = max(1, round(w * skala)), max(1, round(h * skala))
    kecil = cv2.resize(frame_bgr, (lebar, tinggi), interpolation=cv2.INTER_LINEAR)
    kanvas = np.full((ih, iw, 3), WARNA_PAD, dtype=np.uint8)
    kiri, atas = (iw - lebar) // 2, (ih - tinggi) // 2
    kanvas[atas : atas + tinggi, kiri : kiri + lebar] = kecil
    return kanvas, Letterbox(skala, kiri, atas, lebar, tinggi, iw, ih)


def ke_tensor(gambar_bgr: np.ndarray) -> np.ndarray:
    """BGR uint8 (H,W,3) -> float32 RGB NCHW (1,3,H,W) berskala 0-1, kontigu."""
    return np.ascontiguousarray(
        cv2.dnn.blobFromImage(gambar_bgr, scalefactor=1 / 255.0, swapRB=True, crop=False)
    )
