"""Penyimpanan gambar capture: path aman dan tulis JPEG atomik (tmp -> os.replace)."""

import os
import re
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

_CYCLE_ID_AMAN = re.compile(r"[0-9a-zA-Z_-]{1,64}")


class PenyimpananGagal(RuntimeError):
    """Gambar tidak bisa dienkode atau ditulis ke disk (disk penuh, izin, dan sebagainya)."""


def path_gambar(image_dir: Path, cycle_id: str, waktu: datetime) -> Path:
    """Path `image_dir/YYYY-MM-DD/<cycle_id>.jpg`; `cycle_id` tidak aman -> ValueError."""
    if not _CYCLE_ID_AMAN.fullmatch(cycle_id):
        raise ValueError(f"cycle_id tidak aman untuk nama file: {cycle_id!r}")
    return Path(image_dir) / waktu.strftime("%Y-%m-%d") / f"{cycle_id}.jpg"


def simpan_jpeg_atomik(path: Path, frame: np.ndarray, kualitas: int) -> int:
    """Enkode `frame` ke JPEG lalu tulis atomik ke `path`; kembalikan ukuran byte.

    Memakai `imencode` + tulis bytes (bukan `imwrite`, yang gagal diam-diam pada path non-ASCII).
    """
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, int(kualitas)])
    if not ok:
        raise PenyimpananGagal("Gagal mengenkode gambar ke JPEG")
    data = buf.tobytes()
    sementara = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        sementara.write_bytes(data)
        os.replace(sementara, path)
    except OSError as exc:
        try:
            sementara.unlink(missing_ok=True)
        except OSError:
            pass
        raise PenyimpananGagal(f"Gagal menyimpan gambar ke {path}: {exc}") from exc
    return len(data)
