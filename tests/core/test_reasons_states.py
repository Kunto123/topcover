"""Test enum kode alasan, verdict, dan state siklus."""

import re

import pytest

from app.core.reasons import REASON_DESCRIPTIONS, ReasonCode, Verdict
from app.core.states import CycleState


def test_semua_kode_alasan_punya_deskripsi():
    """Setiap ReasonCode wajib punya deskripsi Indonesia tidak kosong."""
    assert set(REASON_DESCRIPTIONS) == set(ReasonCode)
    assert all(teks.strip() for teks in REASON_DESCRIPTIONS.values())


def test_nilai_kode_alasan_unik_dan_snake_case():
    """Nilai string enum menjadi kontrak ke DB/log: unik dan snake_case."""
    nilai = [k.value for k in ReasonCode]
    assert len(nilai) == len(set(nilai))
    assert all(re.fullmatch(r"[a-z]+(_[a-z]+)*", v) for v in nilai)


@pytest.mark.parametrize(
    ("kode", "penilaian"),
    [
        (ReasonCode.CAMPURAN_KIRI_KANAN, True),
        (ReasonCode.WARNA_DI_LUAR_TOLERANSI, True),
        (ReasonCode.KEYAKINAN_RENDAH, True),
        (ReasonCode.TIDAK_ADA_PART, True),
        (ReasonCode.JUMLAH_TIDAK_SESUAI, True),
        (ReasonCode.GAGAL_PUSH, False),
    ],
)
def test_kategori_penilaian(kode, penilaian):
    """Hanya GAGAL_PUSH yang bukan alasan penilaian box."""
    assert kode.is_penilaian is penilaian


def test_verdict_hanya_dua_nilai():
    """Verdict hanya match atau not_match."""
    assert {v.value for v in Verdict} == {"match", "not_match"}


def test_urutan_state_siklus_sesuai_arsitektur():
    """Urutan state harus persis seperti di dokumen arsitektur."""
    assert [s.value for s in CycleState] == [
        "WAIT_DATAPART",
        "READY",
        "CAPTURING",
        "INFERRING",
        "JUDGED",
        "SAVING",
        "PRINTING",
        "DONE",
    ]
