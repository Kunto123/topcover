"""Kode alasan dan verdict terpusat; nilai string adalah kontrak ke database dan log."""

from enum import StrEnum


class Verdict(StrEnum):
    """Hasil penilaian satu box: sesuai datapart atau tidak."""

    MATCH = "match"
    NOT_MATCH = "not_match"


class ReasonCode(StrEnum):
    """Kode alasan hasil/kegagalan siklus. Nilai stabil: jangan diganti setelah dipakai.

    GAGAL_PUSH adalah kegagalan sistem, bukan alasan verdict; rule engine tidak boleh memakainya.
    """

    CAMPURAN_KIRI_KANAN = "campuran_kiri_kanan"
    WARNA_DI_LUAR_TOLERANSI = "warna_di_luar_toleransi"
    KEYAKINAN_RENDAH = "keyakinan_rendah"
    TIDAK_ADA_PART = "tidak_ada_part"
    JUMLAH_TIDAK_SESUAI = "jumlah_tidak_sesuai"
    TIPE_TIDAK_SESUAI = "tipe_tidak_sesuai"
    VARIAN_TIDAK_DIKENAL = "varian_tidak_dikenal"
    GAGAL_PUSH = "gagal_push"

    @property
    def is_penilaian(self) -> bool:
        """True jika kode ini alasan penilaian box; False untuk kegagalan sistem."""
        return self is not ReasonCode.GAGAL_PUSH


REASON_DESCRIPTIONS: dict[ReasonCode, str] = {
    ReasonCode.CAMPURAN_KIRI_KANAN: "Box berisi campuran part kiri dan kanan.",
    ReasonCode.WARNA_DI_LUAR_TOLERANSI: "Warna part di luar toleransi varian datapart.",
    ReasonCode.KEYAKINAN_RENDAH: "Keyakinan model di bawah ambang; diputuskan NOT_MATCH.",
    ReasonCode.TIDAK_ADA_PART: "Tidak ada part terdeteksi pada gambar.",
    ReasonCode.JUMLAH_TIDAK_SESUAI: "Jumlah part terdeteksi tidak sesuai aturan box.",
    ReasonCode.TIPE_TIDAK_SESUAI: "Tipe part (kiri/kanan) tidak sama dengan datapart.",
    ReasonCode.VARIAN_TIDAK_DIKENAL: "Varian warna pada datapart tidak terdaftar.",
    ReasonCode.GAGAL_PUSH: "Gagal mengirim hasil ke database pabrik; ulangi siklus.",
}
