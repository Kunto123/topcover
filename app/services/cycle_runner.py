"""Runner siklus end-to-end: capture -> inferensi -> ukur warna -> aturan box -> simpan -> print.

Kegagalan SEBELUM penilaian membatalkan siklus (event `galat`). Setelah penilaian, semua hasil
berakhir di DONE dengan event `hasil` berstatus eksplisit; print hanya untuk MATCH yang tersimpan.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import FastAPI
from psycopg_pool import ConnectionPool

from app.core.config import Settings
from app.core.logging import bind_cycle_id
from app.core.reasons import Verdict
from app.core.states import CycleState
from app.domain.box_rules import (
    HasilBox,
    KonfigurasiBox,
    PartTerukur,
    VarianWarna,
    nilai_box,
)
from app.domain.color import ukur_warna
from app.domain.cycle_state import MesinSiklus, TransisiTidakValid
from app.domain.types import Datapart
from app.services.camera.pekerja import KameraTidakTersedia, KameraTimeout
from app.services.camera.penyimpanan import PenyimpananGagal
from app.services.inference.tipe import InferensiGagal, ModelTidakSiap
from app.services.printing import (
    KeputusanPrint,
    PrintJob,
    buat_print_port,
    cetak_jika_boleh,
)
from app.services.save_result import (
    GagalPush,
    HasilSimpan,
    LokalGagalSetelahPush,
    PabrikTidakDikonfigurasi,
    SimpanLokalGagal,
    simpan_hasil,
)
from app.storage.local import hasil as hasil_repo
from app.storage.local import konfigurasi as konfigurasi_repo
from app.storage.local import varian as varian_repo
from app.storage.local.skema import DetailPart, RekamanHasil

logger = logging.getLogger("app.cycle_runner")

BATAS_SIKLUS_MS = 10_000

PESAN_STATUS: dict[str, str] = {
    "gagal_push": "Push database pabrik gagal — hasil TIDAK tersimpan. Ulangi siklus.",
    "simpan_lokal_gagal": "Simpan lokal gagal — hasil tidak tersimpan. Ulangi siklus.",
    "tidak_dikonfigurasi": "Database pabrik tidak dikonfigurasi — hasil tidak tersimpan.",
    "lokal_gagal_setelah_push": (
        "Tersimpan di pabrik tetapi gagal disimpan lokal — JANGAN ulangi, panggil SPV."
    ),
    "gagal_cetak": "Hasil tersimpan, tetapi cetak gagal — hubungi teknisi.",
    "galat_internal": "Galat internal setelah penilaian — periksa log (cycle_id).",
}


class _Batalkan(Exception):
    """Siklus dibatalkan sebelum penilaian: `alasan` (kode log) dan `pesan` untuk operator."""

    def __init__(self, alasan: str, pesan: str) -> None:
        """Simpan `alasan` dan `pesan`."""
        super().__init__(pesan)
        self.alasan = alasan
        self.pesan = pesan


@dataclass
class _Lari:
    """Keadaan satu eksekusi runner (agar penanganan galat tahu sampai mana siklus berjalan)."""

    cycle_id: str
    dinilai: bool = False
    hasil_box: HasilBox | None = None
    datapart: Datapart | None = None
    tahap: dict[str, int] = field(default_factory=dict)


def _ms(mulai: float) -> int:
    """Milidetik sejak `mulai` (perf_counter)."""
    return int((time.perf_counter() - mulai) * 1000)


def _ms_dari(siklus: MesinSiklus) -> int:
    """Milidetik sejak siklus masuk READY (scan datapart); 0 bila tidak diketahui."""
    umur = siklus.umur_state(CycleState.READY)
    return int(umur * 1000) if umur is not None else 0


def awal_hari_lokal() -> datetime:
    """Awal hari ini (00:00) waktu lokal PC, aware."""
    return datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)


def hitung_counter(kolam: ConnectionPool | None) -> dict[str, Any] | None:
    """Counter MATCH sejak awal hari dari data lokal; None bila DB tak tersedia."""
    if kolam is None:
        return None
    sejak = awal_hari_lokal()
    try:
        with kolam.connection(timeout=2) as conn:
            n = hasil_repo.hitung_match(conn, sejak)
    except Exception:
        logger.warning("counter_gagal_dihitung")
        return None
    return {"match_hari_ini": n, "sejak": sejak.isoformat()}


class CycleRunner:
    """Menjalankan satu siklus per panggilan `jalankan`; dependensi dibaca dari `app.state`."""

    def __init__(self, app: FastAPI, settings: Settings) -> None:
        """`app` sumber dependensi (`app.state`); `settings` memberi batas waktu."""
        self._app = app
        self._s = settings

    def jalankan(self, cycle_id: str) -> None:
        """Jalankan siklus `cycle_id` (sinkron; dipanggil di thread pekerja oleh /capture)."""
        lari = _Lari(cycle_id)
        with bind_cycle_id(cycle_id):
            try:
                self._jalankan(lari)
            except _Batalkan as b:
                logger.warning("siklus_dibatalkan", extra={"alasan": b.alasan})
                self._batal(b.alasan, b.pesan)
            except Exception:
                logger.exception("siklus_galat", extra={"dinilai": lari.dinilai})
                if lari.dinilai:
                    self._hasil_galat_internal(lari)
                else:
                    self._batal("galat_internal", "Galat internal saat memproses siklus.")

    def _jalankan(self, lari: _Lari) -> None:
        """Alur penuh satu siklus (lihat docstring modul)."""
        st = self._app.state
        siklus: MesinSiklus = st.siklus
        operator = st.sesi.saat_ini()
        if operator is None:
            raise _Batalkan("sesi_berakhir", "Sesi berakhir; login ulang lalu scan lagi.")
        datapart = siklus.datapart
        if datapart is None:
            raise _Batalkan("tanpa_datapart", "Tidak ada datapart aktif.")
        lari.datapart = datapart
        umur = siklus.umur_state(CycleState.READY) or 0.0
        waktu_scan = datetime.now(UTC) - timedelta(seconds=umur)

        # --- CAPTURING ---
        t = time.perf_counter()
        kamera = getattr(st, "kamera", None)
        if kamera is None:
            raise _Batalkan("kamera_gagal", "Kamera tidak aktif.")
        try:
            capture = kamera.ambil_gambar(lari.cycle_id)
        except (KameraTidakTersedia, KameraTimeout, PenyimpananGagal) as exc:
            raise _Batalkan("kamera_gagal", f"Kamera gagal: {exc}") from exc
        lari.tahap["capture"] = _ms(t)
        siklus.pindah(CycleState.INFERRING)

        # --- INFERRING ---
        t = time.perf_counter()
        mesin = getattr(st, "inferensi", None)
        if mesin is None:
            raise _Batalkan("inferensi_gagal", "Mesin inferensi tidak aktif.")
        try:
            inferensi = mesin.deteksi(
                capture.frame,
                cycle_id=lari.cycle_id,
                timeout_s=self._s.siklus_timeout_inferensi_s,
            )
        except (ModelTidakSiap, InferensiGagal) as exc:
            raise _Batalkan("inferensi_gagal", f"Inferensi gagal: {exc}") from exc
        lari.tahap["inferensi"] = _ms(t)

        # --- penilaian ---
        t = time.perf_counter()
        kolam = getattr(st, "db", None)
        if kolam is None:
            raise _Batalkan("penilaian_gagal", "Database lokal tidak tersedia.")
        try:
            varian, kbox, ruang = self._muat_aturan(kolam, datapart)
            parts = [
                PartTerukur(
                    d.kelas,
                    min(1.0, max(0.0, d.keyakinan)),
                    ukur_warna(capture.frame, d.mask, ruang),
                )
                for d in inferensi.deteksi
            ]
            hasil_box = nilai_box(parts, datapart, varian, kbox)
        except Exception as exc:
            raise _Batalkan("penilaian_gagal", f"Penilaian gagal ({type(exc).__name__}).") from exc
        lari.tahap["nilai"] = _ms(t)
        lari.hasil_box = hasil_box
        lari.dinilai = True
        siklus.pindah(CycleState.JUDGED)

        # --- SAVING ---
        rekaman = RekamanHasil(
            cycle_id=lari.cycle_id,
            datapart=datapart.kode,
            varian_warna=datapart.varian_warna,
            verdict=hasil_box.verdict,
            reason_code=hasil_box.alasan,
            operator=operator.username,
            waktu_scan=waktu_scan,
            durasi_total_ms=_ms_dari(siklus),
            tahap_ms=dict(lari.tahap),
            path_gambar=str(capture.path),
            detail_part=[
                DetailPart(
                    kelas=r.kelas,
                    keyakinan=r.keyakinan,
                    warna=r.warna,
                    jarak=r.jarak,
                    ruang_warna=ruang,
                )
                for r in hasil_box.rincian
            ],
        )
        siklus.pindah(CycleState.SAVING)
        status, tersimpan, simpan = self._simpan(kolam, rekaman, lari)
        rekaman_id = simpan.rekaman_id if simpan else None

        # --- PRINTING (hanya MATCH yang tersimpan) ---
        dicetak = False
        pesan_cetak = ""
        if status == "selesai" and hasil_box.verdict is Verdict.MATCH:
            siklus.pindah(CycleState.PRINTING)
            t = time.perf_counter()
            port = getattr(st, "print_port", None)
            if port is None:
                status, pesan_cetak = "gagal_cetak", "Printer tidak aktif."
            else:
                gerbang = cetak_jika_boleh(
                    verdict=hasil_box.verdict,
                    rekaman_id=rekaman_id,
                    job=PrintJob(
                        cycle_id=lari.cycle_id,
                        datapart_kode=datapart.kode,
                        waktu=datetime.now(UTC),
                        payload={"varian_warna": datapart.varian_warna},
                    ),
                    port=port,
                )
                dicetak = gerbang.keputusan is KeputusanPrint.DICETAK
                if not dicetak:
                    status, pesan_cetak = "gagal_cetak", gerbang.pesan
            lari.tahap["print"] = _ms(t)

        self._selesai(
            lari, status, tersimpan, dicetak, pesan_cetak, rekaman_id, kolam, siklus, hasil_box
        )

    def _muat_aturan(
        self, kolam: ConnectionPool, datapart: Datapart
    ) -> tuple[VarianWarna | None, KonfigurasiBox, str]:
        """Baca varian aktif dan konfigurasi terbaru; kembalikan (varian, konfigurasi, ruang)."""
        with kolam.connection(timeout=2) as conn:
            baris = varian_repo.ambil(conn, datapart.varian_warna)
            _, konf = konfigurasi_repo.ambil_terbaru(conn)
        varian = None
        if baris is not None and baris["aktif"]:
            sp = baris["spesifikasi"]
            varian = VarianWarna(baris["nama"], sp.referensi, sp.toleransi, sp.ruang)
        kbox = KonfigurasiBox(
            konf.ambang_keyakinan, konf.jumlah_part_default, konf.izinkan_kurang_dari_default
        )
        return varian, kbox, varian.ruang if varian else konf.ruang_warna

    def _simpan(
        self, kolam: ConnectionPool, rekaman: RekamanHasil, lari: _Lari
    ) -> tuple[str, bool, HasilSimpan | None]:
        """Simpan atomik; kembalikan (status, tersimpan_lokal, hasil). Galat -> status eksplisit."""
        try:
            simpan = simpan_hasil(kolam, getattr(self._app.state, "pabrik", None), rekaman)
        except GagalPush:
            return "gagal_push", False, None
        except PabrikTidakDikonfigurasi:
            return "tidak_dikonfigurasi", False, None
        except SimpanLokalGagal:
            return "simpan_lokal_gagal", False, None
        except LokalGagalSetelahPush:
            return "lokal_gagal_setelah_push", False, None
        lari.tahap.update(simpan.tahap_ms)
        return "selesai", True, simpan

    def _selesai(
        self,
        lari: _Lari,
        status: str,
        tersimpan: bool,
        dicetak: bool,
        pesan_cetak: str,
        rekaman_id: int | None,
        kolam: ConnectionPool,
        siklus: MesinSiklus,
        hasil_box: HasilBox,
    ) -> None:
        """Hitung total, perbarui durasi lokal, siarkan event `hasil`, lalu pindah ke DONE."""
        total_ms = _ms_dari(siklus)
        if rekaman_id is not None:
            try:
                with kolam.connection(timeout=2) as conn:
                    hasil_repo.perbarui_durasi(conn, rekaman_id, total_ms, dict(lari.tahap))
            except Exception:
                logger.warning("durasi_gagal_diperbarui")
        payload = self._payload(lari, status, tersimpan, dicetak, pesan_cetak, total_ms, hasil_box)
        payload["counter"] = hitung_counter(kolam)
        self._app.state.hasil_terakhir = payload
        self._app.state.penyiar.publish("hasil", payload)
        self._ke_done(siklus)
        logger.info(
            "siklus_selesai",
            extra={
                "status": status,
                "verdict": hasil_box.verdict.value,
                "alasan": hasil_box.alasan.value if hasil_box.alasan else None,
                "total_ms": total_ms,
                "lewat_10_detik": total_ms > BATAS_SIKLUS_MS,
                "tahap_ms": lari.tahap,
            },
        )

    def _payload(
        self,
        lari: _Lari,
        status: str,
        tersimpan: bool,
        dicetak: bool,
        pesan_cetak: str,
        total_ms: int,
        hasil_box: HasilBox,
    ) -> dict[str, Any]:
        """Susun payload event `hasil` untuk UI (tanpa data biner)."""
        dp = lari.datapart
        pesan = PESAN_STATUS.get(status)
        if pesan is None:
            pesan = (
                "Semua aturan lolos — datapart dicetak."
                if hasil_box.verdict is Verdict.MATCH
                else hasil_box.pesan
            )
        if status == "gagal_cetak" and pesan_cetak:
            pesan = f"{pesan} ({pesan_cetak})"
        return {
            "cycle_id": lari.cycle_id,
            "status": status,
            "verdict": hasil_box.verdict.value,
            "alasan": hasil_box.alasan.value if hasil_box.alasan else None,
            "pesan": pesan,
            "alasan_penilaian": hasil_box.pesan,
            "semua_alasan": [a.value for a in hasil_box.semua_alasan],
            "tersimpan": tersimpan,
            "tersimpan_di_pabrik": status in ("selesai", "gagal_cetak", "lokal_gagal_setelah_push"),
            "dicetak": dicetak,
            "datapart": None
            if dp is None
            else {
                "kode": dp.kode,
                "tipe": dp.tipe.value,
                "varian_warna": dp.varian_warna,
                "jumlah_isi": dp.jumlah_isi,
            },
            "rincian": [
                {
                    "kelas": r.kelas.value,
                    "keyakinan": round(r.keyakinan, 3),
                    "jarak": None if r.jarak is None else round(r.jarak, 4),
                    "warna": None if r.warna is None else [round(c, 4) for c in r.warna],
                }
                for r in hasil_box.rincian
            ],
            "tahap_ms": dict(lari.tahap),
            "total_ms": total_ms,
            "lewat_10_detik": total_ms > BATAS_SIKLUS_MS,
        }

    def _hasil_galat_internal(self, lari: _Lari) -> None:
        """Galat tak terduga SETELAH penilaian: siarkan status eksplisit, tanpa print."""
        hasil_box = lari.hasil_box
        payload: dict[str, Any] = {
            "cycle_id": lari.cycle_id,
            "status": "galat_internal",
            "verdict": hasil_box.verdict.value if hasil_box else None,
            "alasan": hasil_box.alasan.value if hasil_box and hasil_box.alasan else None,
            "pesan": PESAN_STATUS["galat_internal"],
            "tersimpan": False,
            "dicetak": False,
            "datapart": None,
            "rincian": [],
            "tahap_ms": dict(lari.tahap),
            "total_ms": None,
            "counter": None,
        }
        self._app.state.hasil_terakhir = payload
        self._app.state.penyiar.publish("hasil", payload)
        self._ke_done(self._app.state.siklus)

    def _batal(self, alasan: str, pesan: str) -> None:
        """Batalkan siklus sebelum penilaian dan siarkan `galat` ke UI."""
        siklus: MesinSiklus = self._app.state.siklus
        cycle_id = siklus.cycle_id
        siklus.batalkan(alasan)
        self._app.state.penyiar.publish("galat", {"pesan": pesan, "cycle_id": cycle_id})

    @staticmethod
    def _ke_done(siklus: MesinSiklus) -> None:
        """Pindah ke DONE; bila transisi tak sah (mis. dari JUDGED) batalkan siklus."""
        try:
            siklus.pindah(CycleState.DONE)
        except TransisiTidakValid:
            siklus.batalkan("galat_internal")


def _gerbang_simpan(app: FastAPI) -> Callable[[], str | None]:
    """Bangun gerbang `simpan`: tolak scan datapart bila penyimpanan belum dikonfigurasi."""

    def periksa() -> str | None:
        """Pesan bila DB lokal atau pabrik belum ada, selain itu None."""
        st = app.state
        if getattr(st, "db", None) is None:
            return "Penyimpanan belum siap: database lokal tidak dikonfigurasi."
        if getattr(st, "pabrik", None) is None:
            return "Penyimpanan belum siap: database pabrik tidak dikonfigurasi."
        return None

    return periksa


def pasang(app: FastAPI, settings: Settings) -> None:
    """Pasang runner: `pada_capture`, `print_port`, `hasil_terakhir`, dan gerbang `simpan`."""
    if not settings.siklus_runner_aktif:
        logger.warning("runner_siklus_dimatikan")
        return
    app.state.print_port = buat_print_port(settings)
    app.state.hasil_terakhir = None
    app.state.runner = CycleRunner(app, settings)
    app.state.pada_capture = app.state.runner.jalankan
    app.state.gerbang_mulai["simpan"] = _gerbang_simpan(app)
