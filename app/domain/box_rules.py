"""Aturan penilaian satu box: (part terukur, datapart, varian, konfigurasi) -> verdict + alasan.

Fungsi murni: tanpa log, I/O, waktu, atau random; input tidak diubah. Semua aturan dievaluasi;
alasan utama adalah yang pertama gagal menurut urutan prioritas tetap (kontrak, jangan diubah):

1. TIDAK_ADA_PART  2. KEYAKINAN_RENDAH  3. CAMPURAN_KIRI_KANAN  4. TIPE_TIDAK_SESUAI
5. JUMLAH_TIDAK_SESUAI  6. VARIAN_TIDAK_DIKENAL  7. WARNA_DI_LUAR_TOLERANSI

Ambang bersifat inklusif: keyakinan == ambang lolos; jarak == toleransi lolos.
`ukur_warna` harus dipanggil dengan `varian.ruang` oleh pemanggil. `GAGAL_PUSH` tak dipakai di sini.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.core.reasons import REASON_DESCRIPTIONS, ReasonCode, Verdict
from app.domain.color import Warna, ambil_ruang, jarak_warna
from app.domain.types import Datapart, PartKelas


def _hingga(nilai: float) -> bool:
    """True bila `nilai` bilangan hingga (bukan NaN/inf)."""
    return math.isfinite(nilai)


@dataclass(frozen=True, slots=True)
class PartTerukur:
    """Satu part: `kelas`, `keyakinan` (0-1), `warna` terukur (None = gagal diukur)."""

    kelas: PartKelas
    keyakinan: float
    warna: Warna | None

    def __post_init__(self) -> None:
        """Tolak keyakinan di luar 0-1/NaN dan warna yang tidak hingga."""
        if not _hingga(self.keyakinan) or not 0.0 <= self.keyakinan <= 1.0:
            raise ValueError(f"keyakinan harus 0-1, dapat: {self.keyakinan!r}")
        if self.warna is not None and not all(_hingga(c) for c in self.warna):
            raise ValueError(f"warna harus bilangan hingga, dapat: {self.warna!r}")


@dataclass(frozen=True, slots=True)
class VarianWarna:
    """Varian referensi: `nama`, `referensi` warna, `toleransi` jarak maks, `ruang` warna."""

    nama: str
    referensi: Warna
    toleransi: float
    ruang: str = "lab"

    def __post_init__(self) -> None:
        """Validasi nama, referensi hingga, toleransi > 0, dan ruang terdaftar."""
        if not self.nama.strip():
            raise ValueError("nama varian tidak boleh kosong")
        if not all(_hingga(c) for c in self.referensi):
            raise ValueError(f"referensi harus bilangan hingga, dapat: {self.referensi!r}")
        if not _hingga(self.toleransi) or self.toleransi <= 0:
            raise ValueError(f"toleransi harus > 0, dapat: {self.toleransi!r}")
        ambil_ruang(self.ruang)


@dataclass(frozen=True, slots=True)
class KonfigurasiBox:
    """Pengaturan penilaian: `ambang_keyakinan`, `jumlah_part_default`, izin box kurang lengkap."""

    ambang_keyakinan: float = 0.8
    jumlah_part_default: int = 6
    izinkan_kurang_dari_default: bool = False  # fail-safe: box harus lengkap

    def __post_init__(self) -> None:
        """Validasi ambang 0-1 dan jumlah default >= 1."""
        if not _hingga(self.ambang_keyakinan) or not 0.0 <= self.ambang_keyakinan <= 1.0:
            raise ValueError(f"ambang_keyakinan harus 0-1, dapat: {self.ambang_keyakinan!r}")
        if self.jumlah_part_default < 1:
            raise ValueError("jumlah_part_default harus >= 1")


@dataclass(frozen=True, slots=True)
class RincianPart:
    """Rincian satu part untuk audit: kelas, keyakinan, warna, dan jarak ke referensi varian."""

    kelas: PartKelas
    keyakinan: float
    warna: Warna | None
    jarak: float | None


@dataclass(frozen=True, slots=True)
class HasilBox:
    """Hasil penilaian: `verdict`, `alasan` utama, `semua_alasan` (berurut prioritas), `rincian`."""

    verdict: Verdict
    alasan: ReasonCode | None
    semua_alasan: tuple[ReasonCode, ...]
    rincian: tuple[RincianPart, ...]
    pesan: str


@dataclass(frozen=True, slots=True)
class PeringatanPemisahan:
    """Dua varian `a` dan `b` yang toleransinya tumpang tindih (box salah bisa lolos)."""

    a: str
    b: str
    jarak: float
    jumlah_toleransi: float = field(default=0.0)


def _rincian(parts: Sequence[PartTerukur], varian: VarianWarna | None) -> tuple[RincianPart, ...]:
    """Susun rincian per part; jarak diisi bila varian dan warna tersedia."""
    hasil = []
    for p in parts:
        jarak = None
        if varian is not None and p.warna is not None:
            jarak = jarak_warna(varian.ruang, p.warna, varian.referensi)
        hasil.append(RincianPart(p.kelas, p.keyakinan, p.warna, jarak))
    return tuple(hasil)


def _jumlah_gagal(n: int, datapart: Datapart, konfigurasi: KonfigurasiBox) -> bool:
    """True bila jumlah part `n` tidak sesuai datapart atau aturan default."""
    if datapart.jumlah_isi is not None:
        return n != datapart.jumlah_isi
    batas = konfigurasi.jumlah_part_default
    if konfigurasi.izinkan_kurang_dari_default:
        return not 1 <= n <= batas
    return n != batas


def nilai_box(
    parts: Sequence[PartTerukur],
    datapart: Datapart,
    varian: VarianWarna | None,
    konfigurasi: KonfigurasiBox | None = None,
) -> HasilBox:
    """Nilai satu box: MATCH hanya bila semua aturan lolos; selain itu NOT_MATCH + alasan."""
    konfigurasi = konfigurasi or KonfigurasiBox()

    if len(parts) == 0:
        alasan = ReasonCode.TIDAK_ADA_PART
        return HasilBox(Verdict.NOT_MATCH, alasan, (alasan,), (), REASON_DESCRIPTIONS[alasan])

    gagal: list[ReasonCode] = []
    if any(p.keyakinan < konfigurasi.ambang_keyakinan or p.warna is None for p in parts):
        gagal.append(ReasonCode.KEYAKINAN_RENDAH)

    kelas = {p.kelas for p in parts}
    if len(kelas) > 1:
        gagal.append(ReasonCode.CAMPURAN_KIRI_KANAN)
    elif kelas != {datapart.tipe}:
        gagal.append(ReasonCode.TIPE_TIDAK_SESUAI)

    if _jumlah_gagal(len(parts), datapart, konfigurasi):
        gagal.append(ReasonCode.JUMLAH_TIDAK_SESUAI)

    rincian = _rincian(parts, varian)
    if varian is None or varian.nama != datapart.varian_warna:
        gagal.append(ReasonCode.VARIAN_TIDAK_DIKENAL)
    elif any(r.jarak is not None and r.jarak > varian.toleransi for r in rincian):
        gagal.append(ReasonCode.WARNA_DI_LUAR_TOLERANSI)

    if not gagal:
        return HasilBox(Verdict.MATCH, None, (), rincian, "Semua aturan lolos.")
    utama = gagal[0]
    return HasilBox(Verdict.NOT_MATCH, utama, tuple(gagal), rincian, REASON_DESCRIPTIONS[utama])


def periksa_pemisahan_varian(
    varian: Sequence[VarianWarna], faktor_aman: float = 1.0
) -> list[PeringatanPemisahan]:
    """Cari pasangan varian yang lingkaran toleransinya tumpang tindih (jarak <= (ta+tb)*faktor).

    Pasangan dengan ruang berbeda -> ValueError. Ini peringatan untuk admin, bukan penolakan.
    """
    peringatan: list[PeringatanPemisahan] = []
    for i, a in enumerate(varian):
        for b in varian[i + 1 :]:
            if a.ruang != b.ruang:
                raise ValueError(f"varian {a.nama!r} dan {b.nama!r} beda ruang warna")
            jarak = jarak_warna(a.ruang, a.referensi, b.referensi)
            jumlah = a.toleransi + b.toleransi
            if jarak <= jumlah * faktor_aman:
                peringatan.append(PeringatanPemisahan(a.nama, b.nama, jarak, jumlah))
    return peringatan
