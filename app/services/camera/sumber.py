"""Sumber frame kamera: antarmuka, kamera OpenCV nyata, kamera tiruan untuk uji, kontrol UVC."""

import logging
import math
import sys
import time
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

import cv2
import numpy as np

logger = logging.getLogger("app.camera.sumber")

# Nama kontrol -> properti OpenCV. Hanya dipakai bila kontrol diberikan eksplisit (Spike E).
PROPERTI_UVC: dict[str, int] = {
    "exposure": cv2.CAP_PROP_EXPOSURE,
    "auto_exposure": cv2.CAP_PROP_AUTO_EXPOSURE,
    "gain": cv2.CAP_PROP_GAIN,
    "wb_temperature": cv2.CAP_PROP_WB_TEMPERATURE,
    "auto_wb": cv2.CAP_PROP_AUTO_WB,
    "brightness": cv2.CAP_PROP_BRIGHTNESS,
}


class KameraTidakTersedia(RuntimeError):
    """Kamera tidak bisa dibuka, belum terhubung, atau terputus."""


class SumberFrame(Protocol):
    """Antarmuka sumber frame; hanya satu thread (pekerja) yang boleh memanggilnya."""

    def buka(self) -> None:
        """Buka perangkat; lempar KameraTidakTersedia bila gagal."""
        ...

    def baca(self) -> np.ndarray | None:
        """Baca satu frame BGR uint8, atau None bila gagal."""
        ...

    def tutup(self) -> None:
        """Lepas perangkat (idempoten)."""
        ...

    def properti(self) -> dict[str, Any]:
        """Properti aktual (lebar, tinggi, fps)."""
        ...


def terapkan_kontrol_uvc(
    cap: Any, kontrol: Mapping[str, float]
) -> dict[str, tuple[float, float, bool]]:
    """Set tiap kontrol lalu baca balik; hasil `{nama: (diminta, terbaca, sesuai)}`.

    Nama tak dikenal -> ValueError. `set` yang "berhasil" belum membuktikan efek, maka baca balik.
    """
    hasil: dict[str, tuple[float, float, bool]] = {}
    for nama, nilai in kontrol.items():
        if nama not in PROPERTI_UVC:
            raise ValueError(f"kontrol UVC {nama!r} tidak dikenal; pilih: {sorted(PROPERTI_UVC)}")
        prop = PROPERTI_UVC[nama]
        cap.set(prop, nilai)
        terbaca = float(cap.get(prop))
        sesuai = math.isclose(terbaca, nilai, abs_tol=0.01)
        hasil[nama] = (float(nilai), terbaca, sesuai)
        if not sesuai:
            logger.warning(
                "kontrol_uvc_tidak_sesuai",
                extra={"kontrol": nama, "diminta": nilai, "terbaca": terbaca},
            )
    return hasil


def _pilih_backend(nama: str) -> int:
    """Terjemahkan nama backend ('auto'/'dshow'/'msmf'/'v4l2') ke konstanta OpenCV."""
    if nama == "dshow":
        return cv2.CAP_DSHOW
    if nama == "msmf":
        return cv2.CAP_MSMF
    if nama == "v4l2":
        return cv2.CAP_V4L2
    if sys.platform == "win32":
        return cv2.CAP_DSHOW
    if sys.platform.startswith("linux"):
        return cv2.CAP_V4L2
    return cv2.CAP_ANY


class KameraOpenCV:
    """Kamera USB nyata lewat `cv2.VideoCapture`. Semua I/O ada di `buka()`, bukan konstruktor."""

    def __init__(
        self,
        index: int,
        backend: str,
        lebar: int,
        tinggi: int,
        fps: int,
        kontrol_uvc: Mapping[str, float] | None = None,
    ) -> None:
        """Simpan pengaturan; `kontrol_uvc` kosong/None berarti tidak ada kontrol yang dipaksa."""
        self._index, self._backend = index, backend
        self._lebar, self._tinggi, self._fps = lebar, tinggi, fps
        self._kontrol = dict(kontrol_uvc or {})
        self._cap: Any = None

    def buka(self) -> None:
        """Buka kamera, set resolusi/fps, terapkan kontrol UVC (bila ada), uji baca satu frame."""
        api = _pilih_backend(self._backend)
        cap = cv2.VideoCapture(self._index, api)
        if not cap.isOpened():
            cap.release()
            raise KameraTidakTersedia(
                f"Kamera index {self._index} tidak bisa dibuka (backend {self._backend})"
            )
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._lebar)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._tinggi)
        cap.set(cv2.CAP_PROP_FPS, self._fps)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # diabaikan sebagian backend
        if self._kontrol:
            terapkan_kontrol_uvc(cap, self._kontrol)
        ok, frame = cap.read()
        if not ok or frame is None:
            cap.release()
            raise KameraTidakTersedia(
                f"Kamera index {self._index} terbuka tetapi tidak mengirim frame"
            )
        self._cap = cap
        aktual = self.properti()
        if (aktual["lebar"], aktual["tinggi"]) != (self._lebar, self._tinggi):
            logger.warning(
                "resolusi_kamera_berbeda",
                extra={"diminta": [self._lebar, self._tinggi], "aktual": aktual},
            )
        logger.info("kamera_dibuka", extra={"index": self._index, **aktual})

    def baca(self) -> np.ndarray | None:
        """Baca satu frame; kegagalan -> None."""
        if self._cap is None:
            return None
        ok, frame = self._cap.read()
        return frame if ok and frame is not None else None

    def tutup(self) -> None:
        """Lepas kamera (idempoten)."""
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def properti(self) -> dict[str, Any]:
        """Resolusi dan fps aktual dari perangkat."""
        if self._cap is None:
            return {"lebar": 0, "tinggi": 0, "fps": 0.0}
        return {
            "lebar": int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            "tinggi": int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            "fps": float(self._cap.get(cv2.CAP_PROP_FPS)),
        }


def seq_dari_frame(frame: np.ndarray) -> int:
    """Baca nomor urut yang ditanam `KameraTiruan` pada piksel (0,0) (untuk uji frame segar)."""
    return int(frame[0, 0, 0]) + 256 * int(frame[0, 0, 1])


class KameraTiruan:
    """Kamera palsu untuk uji: frame bernomor, bisa gagal-buka atau putus di tengah.

    Nomor urut ditanam di piksel (0,0) (lihat `seq_dari_frame`); `buka()` ulang memulihkan.
    """

    def __init__(
        self,
        frames: Sequence[np.ndarray] | None = None,
        gagal_buka: bool = False,
        gagal_setelah: int | None = None,
        jeda_s: float = 0.0,
        ukuran: tuple[int, int] = (48, 64),
    ) -> None:
        """`gagal_setelah` = jumlah baca sukses sebelum putus; `jeda_s` = jeda tiap baca."""
        self._frames = list(frames) if frames else None
        self._gagal_buka = gagal_buka
        self._gagal_setelah = gagal_setelah
        self._jeda = jeda_s
        self._ukuran = ukuran
        self._terbuka = False
        self._n = 0
        self.jumlah_buka = 0

    def buka(self) -> None:
        """Buka (atau gagal bila `gagal_buka`); pembukaan ulang memulihkan kamera yang putus."""
        self.jumlah_buka += 1
        if self._gagal_buka:
            raise KameraTidakTersedia("Kamera tiruan: gagal dibuka")
        self._terbuka = True
        self._n = 0
        self._gagal_setelah = None if self.jumlah_buka > 1 else self._gagal_setelah

    def baca(self) -> np.ndarray | None:
        """Hasilkan frame berikutnya; None bila tertutup atau sudah putus."""
        if not self._terbuka:
            return None
        if self._gagal_setelah is not None and self._n >= self._gagal_setelah:
            return None
        if self._jeda:
            time.sleep(self._jeda)
        self._n += 1
        if self._frames:
            return self._frames[(self._n - 1) % len(self._frames)].copy()
        frame = np.zeros((*self._ukuran, 3), np.uint8)
        frame[0, 0] = (self._n % 256, (self._n // 256) % 256, 0)
        return frame

    def tutup(self) -> None:
        """Tutup (idempoten)."""
        self._terbuka = False

    def properti(self) -> dict[str, Any]:
        """Properti tiruan sesuai ukuran frame."""
        return {"lebar": self._ukuran[1], "tinggi": self._ukuran[0], "fps": 30.0}
