"""Endpoint siklus pemeriksaan: scan, capture, reset, state, statistik (CV-6)."""

import logging
from collections.abc import Callable
from typing import Annotated, Any

import anyio.to_thread
from fastapi import APIRouter, BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, StrictStr, StringConstraints

from app.core.config import Settings
from app.core.logging import bind_cycle_id
from app.core.states import CycleState
from app.domain.cycle_state import MesinSiklus, TransisiTidakValid
from app.domain.datapart import DatapartParser, DatapartTidakValid, ParserStub
from app.domain.scan_router import ArahScan, arahkan_scan
from app.services.cycle_runner import hitung_counter
from app.ui.penyiar import Penyiar
from app.ui.routes import TEMPLATES

logger = logging.getLogger("app.api.cycle")

router = APIRouter(prefix="/api/cycle", tags=["siklus"])
router_spike = APIRouter(tags=["spike"])


class PermintaanScan(BaseModel):
    """Badan POST /scan: `kode` hasil tangkapan browser (1-200 karakter, spasi tepi dibuang)."""

    kode: Annotated[
        StrictStr, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ]


def _penangan_rfid_stub(uid: str) -> dict[str, Any] | None:
    """Penangan RFID sementara (diganti CV-5): hanya mencatat panjang kode, bukan isinya."""
    logger.info("rfid_diterima_tanpa_penangan", extra={"panjang": len(uid)})
    return None


def pasang(app: FastAPI, settings: Settings) -> None:
    """Inisialisasi `app.state` siklus dan sambungkan pendengar state ke penyiar SSE."""
    siklus = MesinSiklus()
    penyiar = Penyiar()
    app.state.siklus = siklus
    app.state.penyiar = penyiar
    app.state.parser = ParserStub()
    app.state.status_login = lambda: True  # diganti CV-5
    app.state.penangan_rfid = _penangan_rfid_stub
    app.state.pada_capture = None  # dipasang CV-12
    # Gerbang mulai siklus: nama -> fungsi cepat (tanpa I/O) yang mengembalikan None bila siap,
    # atau pesan Indonesia bila tidak. Tiap layanan mendaftarkan gerbangnya sendiri.
    app.state.gerbang_mulai = {}
    app.state.statistik_scan = {
        "scan_diterima": 0,
        "scan_datapart": 0,
        "scan_rfid": 0,
        "scan_ditolak": 0,
    }
    siklus.tambah_pendengar(lambda _peristiwa: penyiar.publish("state", siklus.ringkasan()))
    app.include_router(router_spike)  # main.py tidak diubah; halaman uji dipasang di sini


def _hitung(request: Request, kunci: str) -> None:
    """Tambah penghitung statistik scan `kunci`."""
    request.app.state.statistik_scan[kunci] += 1


def _gerbang_tertutup(state: Any) -> tuple[str, str] | None:
    """Periksa semua gerbang; kembalikan (nama, pesan) gerbang pertama yang menolak, atau None.

    Gerbang yang melempar exception dianggap tidak siap (fail-safe) dengan pesan generik.
    """
    gerbang: dict[str, Callable[[], str | None]] = state.gerbang_mulai
    for nama, periksa in gerbang.items():
        try:
            pesan = periksa()
        except Exception:
            logger.exception("gerbang_galat", extra={"gerbang": nama})
            return nama, "Pemeriksaan kesiapan gagal."
        if pesan:
            return nama, pesan
    return None


def _respons_tidak_siap(nama: str, pesan: str) -> JSONResponse:
    """Respons 503 seragam untuk gerbang yang menolak."""
    return JSONResponse({"hasil": "tidak_siap", "gerbang": nama, "pesan": pesan}, status_code=503)


@router.post("/scan")
async def scan(badan: PermintaanScan, request: Request) -> JSONResponse:
    """Arahkan scan: RFID ke penangan RFID, datapart ke state machine, atau tolak bila sibuk."""
    state = request.app.state
    siklus: MesinSiklus = state.siklus
    parser: DatapartParser = state.parser
    _hitung(request, "scan_diterima")

    arah = arahkan_scan(bool(state.status_login()), siklus.state)
    if arah is ArahScan.RFID:
        _hitung(request, "scan_rfid")
        try:
            # Penangan boleh melakukan I/O jaringan: jalankan di thread agar event loop bebas.
            login = await anyio.to_thread.run_sync(state.penangan_rfid, badan.kode)
        except Exception as exc:
            # Kode RFID sengaja tidak dicatat; hanya jenis galatnya.
            logger.error("rfid_galat", extra={"jenis": type(exc).__name__})
            return JSONResponse(
                {"hasil": "rfid_galat", "pesan": "Pemrosesan RFID gagal."}, status_code=500
            )
        if login is not None:
            return JSONResponse({"hasil": "rfid", "login": login})
        return JSONResponse({"hasil": "rfid"})
    if arah is ArahScan.SIBUK:
        _hitung(request, "scan_ditolak")
        logger.warning("scan_diabaikan_sibuk", extra={"state": siklus.state.value})
        return JSONResponse(
            {"hasil": "sibuk", "state": siklus.state.value, "pesan": "Siklus sedang berjalan."},
            status_code=409,
        )
    tertutup = _gerbang_tertutup(state)
    if tertutup is not None:
        nama, pesan = tertutup
        _hitung(request, "scan_ditolak")
        logger.warning("scan_ditolak_tidak_siap", extra={"gerbang": nama})
        return _respons_tidak_siap(nama, pesan)
    try:
        datapart = parser.urai(badan.kode)
    except DatapartTidakValid as exc:
        _hitung(request, "scan_ditolak")
        logger.warning("datapart_tidak_valid", extra={"alasan": str(exc)})
        return JSONResponse({"hasil": "datapart_tidak_valid", "pesan": str(exc)}, status_code=422)
    cycle_id = siklus.terima_datapart(datapart)
    _hitung(request, "scan_datapart")
    return JSONResponse(
        {
            "hasil": "datapart",
            "cycle_id": cycle_id,
            "state": siklus.state.value,
            "datapart": siklus.ringkasan()["datapart"],
        }
    )


def _jalankan_capture(request_state: Any, handler: Callable[[str], None], cycle_id: str) -> None:
    """Jalankan penangan capture di thread pekerja; galat -> batalkan siklus dan siarkan `galat`."""
    siklus: MesinSiklus = request_state.siklus
    with bind_cycle_id(cycle_id):
        try:
            handler(cycle_id)
        except Exception as exc:
            logger.exception("capture_error")
            siklus.batalkan("capture_error")
            request_state.penyiar.publish(
                "galat", {"pesan": f"Capture gagal: {type(exc).__name__}", "cycle_id": cycle_id}
            )


@router.post("/capture", status_code=202)
async def capture(request: Request, latar: BackgroundTasks) -> JSONResponse:
    """Mulai capture: hanya dari READY; tanpa penangan terpasang -> 501 dan state tidak berubah."""
    state = request.app.state
    siklus: MesinSiklus = state.siklus
    if siklus.state is not CycleState.READY:
        return JSONResponse(
            {"hasil": "ditolak", "state": siklus.state.value, "pesan": "Belum siap capture."},
            status_code=409,
        )
    tertutup = _gerbang_tertutup(state)  # pertahanan berlapis: gerbang bisa menutup setelah scan
    if tertutup is not None:
        logger.warning("capture_ditolak_tidak_siap", extra={"gerbang": tertutup[0]})
        return _respons_tidak_siap(*tertutup)
    handler = state.pada_capture
    if handler is None:
        return JSONResponse({"pesan": "penangan capture belum dipasang (CV-12)"}, status_code=501)
    try:
        siklus.pindah(CycleState.CAPTURING)
    except TransisiTidakValid as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    cycle_id = siklus.cycle_id or ""
    latar.add_task(_jalankan_capture, state, handler, cycle_id)
    return JSONResponse({"hasil": "diterima", "cycle_id": cycle_id, "state": "CAPTURING"}, 202)


@router.post("/reset")
async def reset(request: Request) -> dict[str, str]:
    """Batalkan siklus berjalan dan kembali menunggu datapart."""
    request.app.state.siklus.batalkan("reset_manual")
    logger.info("siklus_reset")
    return {"hasil": "reset", "state": request.app.state.siklus.state.value}


@router.get("/state")
async def state_siklus(request: Request) -> dict[str, Any]:
    """Ringkasan state siklus saat ini."""
    return request.app.state.siklus.ringkasan()


@router.get("/hasil")
async def hasil_terakhir(request: Request) -> dict[str, Any]:
    """Hasil siklus terakhir (payload event `hasil`), atau `{}` bila belum ada."""
    return getattr(request.app.state, "hasil_terakhir", None) or {}


@router.get("/counter")
async def counter(request: Request) -> JSONResponse:
    """Counter MATCH hari ini dari data lokal; 503 bila database lokal tidak tersedia."""
    kolam = getattr(request.app.state, "db", None)
    hasil = await anyio.to_thread.run_sync(hitung_counter, kolam)
    if hasil is None:
        return JSONResponse({"pesan": "Counter tidak tersedia."}, status_code=503)
    return JSONResponse(hasil)


@router.get("/statistik")
async def statistik(request: Request) -> dict[str, int]:
    """Penghitung scan (dalam memori) untuk uji Spike C."""
    return dict(request.app.state.statistik_scan)


@router_spike.get("/spike/scan", response_class=HTMLResponse)
async def halaman_spike(request: Request) -> HTMLResponse:
    """Halaman uji Spike C (hanya saat `CASING_DEBUG=true`, selain itu 404)."""
    if not request.app.state.settings.debug:
        raise HTTPException(status_code=404)
    return TEMPLATES.TemplateResponse(
        request, "spike_scan.html", {"judul": "Spike C — uji pemindai", "konfig_scan": {}}
    )
