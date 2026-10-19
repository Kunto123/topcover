"""Pelari model: antarmuka tipis di atas OpenVINO, plus pelari tiruan untuk test."""

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from app.services.inference.tipe import ModelGagalDimuat


@dataclass(frozen=True, slots=True)
class InfoModel:
    """Info model termuat: `ukuran_input` (tinggi, lebar), kanal output0, dan kanal proto mask."""

    ukuran_input: tuple[int, int]
    kanal_output: int
    kanal_proto: int


class Pelari(Protocol):
    """Antarmuka pelari; instance hanya boleh dipakai dari satu thread pada satu waktu."""

    def muat(self, path: Path) -> InfoModel:
        """Muat model dari `path` (berkas .xml atau folder berisi satu .xml)."""
        ...

    def jalankan(self, tensor: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Jalankan model pada tensor (1,3,H,W); kembalikan (output0, output1) salinan."""
        ...

    def tutup(self) -> None:
        """Lepas sumber daya (idempoten)."""
        ...


def cari_xml(path: Path) -> Path:
    """Temukan berkas .xml model: `path` sendiri atau satu-satunya .xml di folder."""
    if path.is_file():
        if path.suffix.lower() != ".xml":
            raise ModelGagalDimuat(f"Berkas model harus .xml (OpenVINO IR): {path}")
        return path
    if not path.is_dir():
        raise ModelGagalDimuat(f"Model tidak ditemukan: {path}")
    kandidat = sorted(path.glob("*.xml"))
    if len(kandidat) != 1:
        raise ModelGagalDimuat(
            f"Folder model harus berisi tepat satu .xml (ada {len(kandidat)}): {path}"
        )
    return kandidat[0]


class PelariOpenVINO:
    """Memuat IR OpenVINO statis dan menjalankan inferensi dengan hint LATENCY."""

    def __init__(self, device: str = "CPU", threads: int | None = None) -> None:
        """`device` target OpenVINO; `threads` batas thread inferensi (None = otomatis)."""
        import openvino as ov  # diimpor di sini agar modul lain tetap bisa diimpor tanpa openvino

        self._ov = ov
        self._device = device
        self._threads = threads
        self._compiled = None
        self._req = None

    def muat(self, path: Path) -> InfoModel:
        """Baca, validasi (statis, 2 output: deteksi 3-D dan proto 4-D), compile, dan siapkan."""
        xml = cari_xml(path)
        core = self._ov.Core()
        try:
            model = core.read_model(str(xml))
        except Exception as exc:
            raise ModelGagalDimuat(f"Gagal membaca model {xml.name}: {exc}") from exc
        masukan = model.input(0).get_partial_shape()
        if masukan.is_dynamic or masukan.rank.get_length() != 4:
            raise ModelGagalDimuat(
                "Model harus berbentuk statis (1,3,H,W); ekspor dengan dynamic=False."
            )
        _, _, tinggi, lebar = (int(d) for d in masukan.get_shape())
        config = {"PERFORMANCE_HINT": "LATENCY", "NUM_STREAMS": "1"}
        if self._threads:
            config["INFERENCE_NUM_THREADS"] = str(self._threads)
        try:
            self._compiled = core.compile_model(model, self._device, config)
        except Exception as exc:
            raise ModelGagalDimuat(f"Gagal compile model di {self._device}: {exc}") from exc
        bentuk = [o.get_partial_shape() for o in self._compiled.outputs]
        if len(bentuk) != 2 or any(b.is_dynamic for b in bentuk):
            raise ModelGagalDimuat("Bukan model segmentasi YOLO (butuh 2 output statis).")
        rank = [b.rank.get_length() for b in bentuk]
        if sorted(rank) != [3, 4]:
            raise ModelGagalDimuat(f"Bentuk output tidak dikenal (rank {rank}).")
        self._i_deteksi = rank.index(3)
        self._i_proto = rank.index(4)
        self._req = self._compiled.create_infer_request()
        return InfoModel(
            (tinggi, lebar),
            int(bentuk[self._i_deteksi].get_shape()[1]),
            int(bentuk[self._i_proto].get_shape()[1]),
        )

    def jalankan(self, tensor: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Inferensi satu tensor; salin keluaran karena buffer permintaan dipakai ulang."""
        if self._req is None:
            raise ModelGagalDimuat("Model belum dimuat.")
        self._req.infer({0: tensor})
        o0 = np.array(self._req.get_output_tensor(self._i_deteksi).data, copy=True)
        o1 = np.array(self._req.get_output_tensor(self._i_proto).data, copy=True)
        return o0, o1

    def tutup(self) -> None:
        """Lepas permintaan dan model (idempoten)."""
        self._req = None
        self._compiled = None


class PelariTiruan:
    """Pelari untuk test: mengembalikan tensor yang disuntik; opsional lambat atau galat."""

    def __init__(
        self,
        output0: np.ndarray,
        output1: np.ndarray,
        ukuran_input: tuple[int, int] = (64, 64),
        tunda_s: float = 0.0,
    ) -> None:
        """`output0`/`output1` dikembalikan apa adanya; `tunda_s` jeda tiap `jalankan`."""
        self.output0, self.output1 = output0, output1
        self.ukuran_input = ukuran_input
        self.tunda_s = tunda_s
        self.galat: Exception | None = None
        self.gagal_muat: Exception | None = None
        self.jumlah_jalan = 0
        self.tertutup = False
        self.sedang_jalan = 0
        self.tumpang_tindih = False

    def muat(self, path: Path) -> InfoModel:
        """Kembalikan info dari bentuk tensor yang disuntik (atau lempar `gagal_muat`)."""
        if self.gagal_muat is not None:
            raise self.gagal_muat
        return InfoModel(self.ukuran_input, self.output0.shape[1], self.output1.shape[1])

    def jalankan(self, tensor: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Kembalikan tensor suntikan; catat bila dua panggilan tumpang tindih."""
        self.sedang_jalan += 1
        if self.sedang_jalan > 1:
            self.tumpang_tindih = True
        try:
            self.jumlah_jalan += 1
            if self.tunda_s:
                time.sleep(self.tunda_s)
            if self.galat is not None:
                raise self.galat
            return self.output0.copy(), self.output1.copy()
        finally:
            self.sedang_jalan -= 1

    def tutup(self) -> None:
        """Tandai tertutup."""
        self.tertutup = True
