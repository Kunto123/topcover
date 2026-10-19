"""Mesin inferensi: memuat model, satu thread pekerja, tukar model atomik, dan status."""

import logging
import threading
import time
from collections import Counter
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.core.config import Settings
from app.core.logging import bind_cycle_id
from app.domain.types import PartKelas
from app.services.inference.pascaproses import dekode
from app.services.inference.pelari import InfoModel, Pelari
from app.services.inference.praproses import ke_tensor, letterbox
from app.services.inference.tipe import (
    HasilInferensi,
    InferensiGagal,
    InferensiTimeout,
    ModelGagalDimuat,
    ModelTidakSiap,
)

logger = logging.getLogger("app.inference.mesin")


@dataclass(slots=True)
class _Model:
    """Model termuat: pelari, versi, urutan kelas, dan info bentuk."""

    pelari: Pelari
    versi: str
    kelas: list[PartKelas]
    info: InfoModel


def petakan_kelas(nama_kelas: list[str]) -> list[PartKelas]:
    """Petakan nama kelas model ke `PartKelas` (tak peka huruf); selain kiri/kanan -> galat."""
    hasil: list[PartKelas] = []
    for nama in nama_kelas:
        try:
            hasil.append(PartKelas(nama.strip().lower()))
        except ValueError as exc:
            raise ModelGagalDimuat(
                f"Nama kelas model {nama!r} tidak sah; hanya 'kiri' dan 'kanan'."
            ) from exc
    if len(set(hasil)) != len(hasil):
        raise ModelGagalDimuat("Nama kelas model ganda.")
    return hasil


class MesinInferensi:
    """Memuat model aktif dan menjalankan deteksi di satu thread pekerja."""

    def __init__(self, pabrik_pelari: Callable[[], Pelari], settings: Settings) -> None:
        """`pabrik_pelari` membuat pelari baru tiap pemuatan; `settings` memberi ambang."""
        self._pabrik = pabrik_pelari
        self._s = settings
        self._lock = threading.Lock()
        self._model: _Model | None = None
        self._galat: str | None = None
        self._macet: Future | None = None
        self._terakhir_ms: float | None = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="inferensi")

    # ---------- pemuatan ----------

    def _bangun(self, path: Path, versi: str, nama_kelas: list[str]) -> _Model:
        """Muat ke pelari baru, validasi kelas/kanal, warm-up; gagal -> ModelGagalDimuat."""
        kelas = petakan_kelas(nama_kelas)
        pelari = self._pabrik()
        try:
            try:
                info = pelari.muat(path)
            except ModelGagalDimuat:
                raise
            except Exception as exc:
                raise ModelGagalDimuat(f"Gagal memuat model {versi}: {exc}") from exc
            if info.kanal_output != 4 + len(kelas) + info.kanal_proto:
                raise ModelGagalDimuat(
                    f"Jumlah kelas model tidak cocok: output {info.kanal_output} kanal, "
                    f"{len(kelas)} kelas terdaftar + {info.kanal_proto} koefisien mask."
                )
            h, w = info.ukuran_input
            try:
                pelari.jalankan(np.zeros((1, 3, h, w), dtype=np.float32))  # warm-up
            except Exception as exc:
                raise ModelGagalDimuat(f"Warm-up model {versi} gagal: {exc}") from exc
            return _Model(pelari, versi, kelas, info)
        except BaseException:
            pelari.tutup()
            raise

    def periksa(self, path: Path, nama_kelas: list[str]) -> InfoModel:
        """Validasi model (kelas, kanal, bisa dimuat + warm-up) TANPA mengubah model aktif."""
        model = self._bangun(path, "periksa", nama_kelas)
        model.pelari.tutup()
        return model.info

    def muat(self, path: Path, versi: str, nama_kelas: list[str]) -> None:
        """Muat model awal; gagal -> catat galat dan lempar ModelGagalDimuat."""
        try:
            baru = self._bangun(path, versi, nama_kelas)
        except ModelGagalDimuat as exc:
            with self._lock:
                self._galat = str(exc)
            logger.error("model_gagal_dimuat", extra={"versi": versi, "alasan": str(exc)})
            raise
        self._tukar(baru)
        logger.info("model_dimuat", extra={"versi": versi, "ukuran_input": baru.info.ukuran_input})

    def muat_ulang(self, path: Path, versi: str, nama_kelas: list[str]) -> None:
        """Ganti model tanpa menghentikan yang lama; gagal -> model lama dipertahankan."""
        try:
            baru = self._bangun(path, versi, nama_kelas)
        except ModelGagalDimuat as exc:
            with self._lock:
                self._galat = str(exc)
            logger.error("model_muat_ulang_gagal", extra={"versi": versi, "alasan": str(exc)})
            raise
        self._tukar(baru)
        logger.info("model_diganti", extra={"versi": versi})

    def _tukar(self, baru: _Model) -> None:
        """Pasang `baru`; model lama ditutup di thread pekerja agar tidak bentrok inferensi."""

        def kerja() -> None:
            """Tukar dan tutup model lama (berjalan di thread pekerja)."""
            with self._lock:
                lama, self._model, self._galat = self._model, baru, None
            if lama is not None:
                lama.pelari.tutup()

        try:
            self._executor.submit(kerja).result(timeout=30)
        except RuntimeError:  # executor sudah dimatikan
            baru.pelari.tutup()

    # ---------- penggunaan ----------

    def catat_galat(self, pesan: str) -> None:
        """Simpan pesan galat pemuatan (tampil di status dan gerbang mulai)."""
        with self._lock:
            self._galat = pesan

    @property
    def siap(self) -> bool:
        """True bila ada model termuat."""
        with self._lock:
            return self._model is not None

    @property
    def galat(self) -> str | None:
        """Pesan galat pemuatan terakhir (None bila tidak ada)."""
        with self._lock:
            return self._galat

    def _kerja(self, model: _Model, frame: np.ndarray, cycle_id: str) -> HasilInferensi:
        """Pra-proses, inferensi, pasca-proses satu frame (berjalan di thread pekerja)."""
        with bind_cycle_id(cycle_id):
            t0 = time.perf_counter()
            kanvas, lb = letterbox(frame, model.info.ukuran_input)
            tensor = ke_tensor(kanvas)
            t1 = time.perf_counter()
            o0, o1 = model.pelari.jalankan(tensor)
            t2 = time.perf_counter()
            deteksi = dekode(
                o0,
                o1,
                letterbox=lb,
                ukuran_frame=frame.shape[:2],
                kelas=model.kelas,
                ambang_deteksi=self._s.inference_ambang_deteksi,
                ambang_mask=self._s.inference_ambang_mask,
                maks_deteksi=self._s.inference_maks_deteksi,
            )
            t3 = time.perf_counter()
            tahap = {
                "praproses": round((t1 - t0) * 1000, 1),
                "infer": round((t2 - t1) * 1000, 1),
                "pascaproses": round((t3 - t2) * 1000, 1),
                "total": round((t3 - t0) * 1000, 1),
            }
            self._terakhir_ms = tahap["total"]
            logger.info(
                "inferensi_selesai",
                extra={
                    "versi": model.versi,
                    "jumlah": dict(Counter(d.kelas.value for d in deteksi)),
                    "tahap_ms": tahap,
                },
            )
            return HasilInferensi(
                tuple(deteksi), tahap, model.versi, (frame.shape[0], frame.shape[1])
            )

    def deteksi(
        self, frame: np.ndarray, *, cycle_id: str, timeout_s: float = 5.0
    ) -> HasilInferensi:
        """Deteksi part pada `frame` BGR; galat: ModelTidakSiap/InferensiTimeout/InferensiGagal."""
        with self._lock:
            model, galat, macet = self._model, self._galat, self._macet
        if model is None:
            raise ModelTidakSiap(galat or "Model belum dimuat.")
        if macet is not None:
            if not macet.done():
                raise ModelTidakSiap("Pekerja inferensi masih memproses frame sebelumnya.")
            self._macet = None
        try:
            future = self._executor.submit(self._kerja, model, frame, cycle_id)
        except RuntimeError as exc:
            raise ModelTidakSiap("Mesin inferensi sudah dihentikan.") from exc
        try:
            return future.result(timeout=timeout_s)
        except FutureTimeout as exc:
            self._macet = future
            logger.error("inferensi_timeout", extra={"timeout_s": timeout_s, "cycle_id": cycle_id})
            raise InferensiTimeout(f"Inferensi melewati {timeout_s} detik.") from exc
        except InferensiGagal:
            raise
        except Exception as exc:
            raise InferensiGagal(f"Inferensi gagal ({type(exc).__name__}): {exc}") from exc

    def status(self) -> dict:
        """Status untuk UI/API: siap, versi, device, galat, ukuran input, latensi terakhir."""
        with self._lock:
            model, galat = self._model, self._galat
        return {
            "siap": model is not None,
            "versi": model.versi if model else None,
            "device": self._s.inference_device,
            "galat": galat,
            "ukuran_input": list(model.info.ukuran_input) if model else None,
            "inferensi_terakhir_ms": self._terakhir_ms,
        }

    def henti(self) -> None:
        """Hentikan pekerja dan tutup model (idempoten)."""
        self._executor.shutdown(wait=False, cancel_futures=True)
        with self._lock:
            model, self._model = self._model, None
        if model is not None:
            model.pelari.tutup()
