"""Skema pydantic untuk isi JSONB dan rekaman hasil; divalidasi SEBELUM ditulis ke database."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.reasons import ReasonCode, Verdict
from app.domain.types import PartKelas

Tiga = tuple[float, float, float]
RuangWarnaNama = Literal["lab", "ycrcb", "hsv"]


class SkemaTidakValid(RuntimeError):
    """Data JSONB di database tidak sesuai skema (mis. data lama melenceng); pesan memuat asal."""


class _Dasar(BaseModel):
    """Dasar skema: kunci tak dikenal ditolak dan objek tidak bisa diubah."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class DetailPart(_Dasar):
    """Satu part pada hasil: kelas, keyakinan 0-1, warna terukur, jarak, ruang warna."""

    kelas: PartKelas
    keyakinan: float = Field(ge=0.0, le=1.0)
    warna: Tiga | None = None
    jarak: float | None = Field(default=None, ge=0.0)
    ruang_warna: str


class SpesifikasiVarian(_Dasar):
    """Spesifikasi varian warna: warna `referensi`, `toleransi` (> 0), dan `ruang` warna."""

    referensi: Tiga
    toleransi: float = Field(gt=0.0)
    ruang: RuangWarnaNama = "lab"


class MetadataModel(_Dasar):
    """Metadata model: nama kelas (tidak kosong), format asal, ukuran input, catatan."""

    nama_kelas: list[str] = Field(min_length=1)
    format_asal: str
    ukuran_input: tuple[int, int] | None = None
    catatan: str | None = None


class KonfigurasiAplikasi(_Dasar):
    """Konfigurasi aplikasi berversi: ambang keyakinan, masa simpan, ruang warna, jumlah part."""

    ambang_keyakinan: float = Field(default=0.8, ge=0.0, le=1.0)
    masa_simpan_gambar_hari: int = Field(default=3, ge=1)
    ruang_warna: RuangWarnaNama = "lab"
    jumlah_part_default: int = Field(default=6, ge=1)
    izinkan_kurang_dari_default: bool = False


class RekamanHasil(_Dasar):
    """Satu rekaman hasil pemeriksaan siap simpan; konsistensi verdict dan alasan ditegakkan."""

    cycle_id: str = Field(min_length=1)
    datapart: str = Field(min_length=1)
    varian_warna: str | None = None
    verdict: Verdict
    reason_code: ReasonCode | None = None
    operator: str = Field(min_length=1)
    waktu_scan: datetime
    durasi_total_ms: int | None = Field(default=None, ge=0)
    tahap_ms: dict[str, int] = Field(default_factory=dict)
    path_gambar: str | None = None
    detail_part: list[DetailPart] = Field(default_factory=list)

    @field_validator("waktu_scan")
    @classmethod
    def _harus_aware(cls, nilai: datetime) -> datetime:
        """Tolak datetime tanpa zona waktu (kolom timestamptz butuh zona yang jelas)."""
        if nilai.tzinfo is None:
            raise ValueError("waktu_scan harus timezone-aware")
        return nilai

    @model_validator(mode="after")
    def _konsisten_verdict_alasan(self) -> "RekamanHasil":
        """MATCH tanpa alasan; NOT_MATCH wajib beralasan penilaian (bukan GAGAL_PUSH)."""
        if self.verdict is Verdict.MATCH and self.reason_code is not None:
            raise ValueError("verdict MATCH tidak boleh punya reason_code")
        if self.verdict is Verdict.NOT_MATCH:
            if self.reason_code is None:
                raise ValueError("verdict NOT_MATCH wajib punya reason_code")
            if not self.reason_code.is_penilaian:
                raise ValueError(f"{self.reason_code.value} bukan alasan penilaian box")
        return self
