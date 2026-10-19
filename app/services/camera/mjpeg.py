"""Preview MJPEG: enkode frame yang diperkecil dan alirkan sebagai multipart tanpa blokir loop."""

import asyncio
from collections.abc import AsyncIterator
from typing import Protocol

import cv2
import numpy as np

BATAS = b"--frame\r\n"
_placeholder_cache: bytes | None = None


class _Pekerja(Protocol):
    """Bentuk minimal pekerja kamera yang dibutuhkan aliran."""

    def frame_terakhir(self) -> tuple[np.ndarray, int] | None:
        """Frame terakhir dan seq-nya, atau None bila kamera tidak tersedia."""


class _Klien(Protocol):
    """Bentuk minimal klien HTTP."""

    async def is_disconnected(self) -> bool:
        """True jika klien sudah memutus koneksi."""


def enkode_preview(frame: np.ndarray, lebar: int, kualitas: int = 75) -> bytes:
    """Perkecil `frame` ke `lebar` (proporsional, hanya bila lebih lebar) lalu enkode JPEG."""
    tinggi_asal, lebar_asal = frame.shape[:2]
    if lebar_asal > lebar:
        tinggi = max(1, round(tinggi_asal * lebar / lebar_asal))
        frame = cv2.resize(frame, (lebar, tinggi), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, kualitas])
    if not ok:
        raise RuntimeError("Gagal mengenkode frame preview")
    return buf.tobytes()


def placeholder_jpeg() -> bytes:
    """Gambar 'KAMERA TIDAK TERSEDIA' (dibuat sekali, lalu di-cache)."""
    global _placeholder_cache
    if _placeholder_cache is None:
        gambar = np.full((270, 480, 3), 40, np.uint8)
        cv2.putText(
            gambar,
            "KAMERA TIDAK TERSEDIA",
            (40, 145),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.9,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
        _placeholder_cache = enkode_preview(gambar, 480)
    return _placeholder_cache


def bagian_mjpeg(jpeg: bytes) -> bytes:
    """Bungkus satu JPEG menjadi bagian multipart `--frame`."""
    kepala = b"Content-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n" % len(jpeg)
    return BATAS + kepala + jpeg + b"\r\n"


async def aliran_mjpeg(
    pekerja: _Pekerja, request: _Klien, fps: float, lebar: int
) -> AsyncIterator[bytes]:
    """Alirkan frame terbaru (tanpa mengulang `seq` yang sama) sampai klien putus.

    Tanpa frame (kamera mati) kirim placeholder tiap detik; aliran tidak ditutup.
    """
    seq_terakhir = -1
    jeda = 1.0 / max(fps, 0.1)
    while not await request.is_disconnected():
        hasil = pekerja.frame_terakhir()
        if hasil is None:
            seq_terakhir = -1
            yield bagian_mjpeg(placeholder_jpeg())
            await asyncio.sleep(1.0)
            continue
        frame, seq = hasil
        if seq != seq_terakhir:
            jpeg = await asyncio.to_thread(enkode_preview, frame, lebar)
            seq_terakhir = seq
            yield bagian_mjpeg(jpeg)
        await asyncio.sleep(jeda)
