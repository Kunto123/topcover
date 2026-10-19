"""Pemetaan kolom tabel pabrik dari berkas JSON (skema final pabrik: TBD).

Nama tabel/kolom divalidasi ketat karena masuk ke SQL sebagai identifier, bukan nilai.
"""

import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints, ValidationError, model_validator

NamaSql = Annotated[str, StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")]
KolomHasil = Literal[
    "cycle_id",
    "datapart",
    "verdict",
    "reason_code",
    "operator",
    "waktu_scan",
    "waktu_simpan",
    "durasi_total_ms",
    "path_gambar",
]
KolomOperator = Literal["username", "kredensial", "aktif", "rfid", "peran", "nama"]


class PemetaanTidakValid(ValueError):
    """Berkas pemetaan pabrik tidak bisa dibaca atau tidak sesuai skema; pesan memuat asal."""


class _Dasar(BaseModel):
    """Dasar skema: kunci tak dikenal ditolak dan objek tidak bisa diubah."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class TabelHasil(_Dasar):
    """Tabel tujuan hasil: `kolom` memetakan nama logis ke kolom pabrik; `nilai_tetap` konstanta."""

    skema: NamaSql = "public"
    nama: NamaSql
    kolom: dict[KolomHasil, NamaSql]
    nilai_verdict: dict[Literal["match", "not_match"], str] = {
        "match": "match",
        "not_match": "not_match",
    }
    nilai_tetap: dict[NamaSql, str | int | bool] = {}

    @model_validator(mode="after")
    def _periksa(self) -> "TabelHasil":
        """Kolom wajib ada, kolom tujuan tidak ganda, dan kedua nilai verdict terdefinisi."""
        for wajib in ("datapart", "verdict", "operator"):
            if wajib not in self.kolom:
                raise ValueError(f"kolom wajib belum dipetakan: {wajib}")
        tujuan = [*self.kolom.values(), *self.nilai_tetap.keys()]
        ganda = sorted({k for k in tujuan if tujuan.count(k) > 1})
        if ganda:
            raise ValueError(f"kolom tujuan ganda: {', '.join(ganda)}")
        if set(self.nilai_verdict) != {"match", "not_match"}:
            raise ValueError("nilai_verdict harus memuat match dan not_match")
        return self


class TabelOperator(_Dasar):
    """Tabel operator pabrik; `nilai_aktif` WAJIB eksplisit (nilai kolom yang berarti aktif)."""

    skema: NamaSql = "public"
    nama: NamaSql
    kolom: dict[KolomOperator, NamaSql]
    nilai_aktif: list[str | int | bool]

    @model_validator(mode="after")
    def _periksa(self) -> "TabelOperator":
        """Kolom username/kredensial/aktif wajib; `nilai_aktif` tidak boleh kosong."""
        for wajib in ("username", "kredensial", "aktif"):
            if wajib not in self.kolom:
                raise ValueError(f"kolom operator wajib belum dipetakan: {wajib}")
        if not self.nilai_aktif:
            raise ValueError("nilai_aktif tidak boleh kosong")
        return self


class PemetaanPabrik(_Dasar):
    """Pemetaan lengkap: `versi` berkas, tabel `hasil`, dan tabel `operator` (opsional)."""

    versi: int
    hasil: TabelHasil
    operator: TabelOperator | None = None


def muat_pemetaan(path: str | Path) -> PemetaanPabrik:
    """Baca dan validasi berkas pemetaan JSON; galat -> PemetaanTidakValid memuat path."""
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PemetaanTidakValid(f"{p}: tidak bisa dibaca ({type(exc).__name__})") from exc
    try:
        return PemetaanPabrik.model_validate(data)
    except ValidationError as exc:
        detail = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
        raise PemetaanTidakValid(f"{p}: {detail}") from exc
