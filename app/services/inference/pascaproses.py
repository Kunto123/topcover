"""Pasca-proses keluaran YOLO11-seg: decode kotak, NMS per kelas, dan mask ukuran frame.

Ambang di sini sengaja RENDAH (deteksi ragu tetap dilaporkan); keputusan "ragu -> NOT_MATCH"
milik rule engine (CV-2). NMS dilakukan PER KELAS: part yang sama terdeteksi sebagai kiri dan
kanan harus tampil dua-duanya agar rule engine melihat campuran (fail-safe).
"""

import cv2
import numpy as np

from app.domain.types import PartKelas
from app.services.inference.praproses import Letterbox
from app.services.inference.tipe import DeteksiPart, InferensiGagal

IOU_NMS = 0.5


def _sigmoid(x: np.ndarray) -> np.ndarray:
    """Sigmoid stabil secara numerik."""
    return 1.0 / (1.0 + np.exp(-np.clip(x, -50.0, 50.0)))


def _mask_frame(
    koef: np.ndarray,
    proto: np.ndarray,
    lb: Letterbox,
    ukuran_frame: tuple[int, int],
    bbox: tuple[int, int, int, int],
    ambang_mask: float,
) -> np.ndarray:
    """Mask bool (H, W) dari koefisien x prototipe, dibuang pad letterbox lalu dipotong ke bbox."""
    h, w = ukuran_frame
    nm, ph, pw = proto.shape
    peta = _sigmoid(koef @ proto.reshape(nm, -1)).reshape(ph, pw).astype(np.float32)
    x0 = round(lb.kiri * pw / lb.input_w)
    x1 = max(x0 + 1, round((lb.kiri + lb.lebar) * pw / lb.input_w))
    y0 = round(lb.atas * ph / lb.input_h)
    y1 = max(y0 + 1, round((lb.atas + lb.tinggi) * ph / lb.input_h))
    penuh = cv2.resize(peta[y0:y1, x0:x1], (w, h), interpolation=cv2.INTER_LINEAR)
    mask = np.zeros((h, w), dtype=bool)
    bx1, by1, bx2, by2 = bbox
    mask[by1:by2, bx1:bx2] = penuh[by1:by2, bx1:bx2] > ambang_mask
    return mask


def dekode(
    output0: np.ndarray,
    output1: np.ndarray,
    *,
    letterbox: Letterbox,
    ukuran_frame: tuple[int, int],
    kelas: list[PartKelas],
    ambang_deteksi: float,
    ambang_mask: float,
    maks_deteksi: int,
) -> list[DeteksiPart]:
    """Ubah tensor mentah menjadi `DeteksiPart` (keyakinan menurun, maks `maks_deteksi`).

    `ukuran_frame` = (tinggi, lebar) frame asli; `kelas` urutan kelas model.
    """
    if output0.ndim != 3 or output0.shape[0] != 1 or output1.ndim != 4 or output1.shape[0] != 1:
        raise InferensiGagal(f"bentuk keluaran tidak dikenal: {output0.shape} / {output1.shape}")
    nc, nm = len(kelas), output1.shape[1]
    if output0.shape[1] != 4 + nc + nm:
        raise InferensiGagal(
            f"kanal keluaran {output0.shape[1]} != 4 + {nc} kelas + {nm} koefisien mask"
        )
    pred = output0[0].T  # (N, 4 + nc + nm)
    skor_kelas = pred[:, 4 : 4 + nc]
    id_kelas = skor_kelas.argmax(axis=1)
    skor = skor_kelas[np.arange(pred.shape[0]), id_kelas]
    lolos = np.flatnonzero(skor >= ambang_deteksi)
    if lolos.size == 0:
        return []

    h, w = ukuran_frame
    cx, cy, bw, bh = (pred[lolos, i] for i in range(4))
    x1 = np.clip((cx - bw / 2 - letterbox.kiri) / letterbox.skala, 0, w)
    y1 = np.clip((cy - bh / 2 - letterbox.atas) / letterbox.skala, 0, h)
    x2 = np.clip((cx + bw / 2 - letterbox.kiri) / letterbox.skala, 0, w)
    y2 = np.clip((cy + bh / 2 - letterbox.atas) / letterbox.skala, 0, h)

    terpilih: list[int] = []
    for k in range(nc):
        idx = np.flatnonzero(id_kelas[lolos] == k)
        if idx.size == 0:
            continue
        kotak = [
            [float(x1[i]), float(y1[i]), float(x2[i] - x1[i]), float(y2[i] - y1[i])] for i in idx
        ]
        simpan = cv2.dnn.NMSBoxes(kotak, [float(skor[lolos[i]]) for i in idx], 0.0, IOU_NMS)
        terpilih.extend(int(idx[j]) for j in np.array(simpan).reshape(-1))
    terpilih.sort(key=lambda i: -float(skor[lolos[i]]))
    terpilih = terpilih[:maks_deteksi]

    proto = output1[0]
    hasil: list[DeteksiPart] = []
    for i in terpilih:
        bbox = (int(x1[i]), int(y1[i]), int(np.ceil(x2[i])), int(np.ceil(y2[i])))
        koef = pred[lolos[i], 4 + nc :]
        mask = _mask_frame(koef, proto, letterbox, ukuran_frame, bbox, ambang_mask)
        hasil.append(DeteksiPart(kelas[int(id_kelas[lolos[i]])], float(skor[lolos[i]]), bbox, mask))
    return hasil
