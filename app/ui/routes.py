"""Route halaman kiosk, health check, dan aliran SSE."""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Protocol

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from app.ui.penyiar import Penyiar, format_sse

UI_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(UI_DIR / "templates"))
INTERVAL_KEEPALIVE_DETIK = 15.0

router = APIRouter()


class _KlienSSE(Protocol):
    """Bentuk minimal klien yang dibutuhkan aliran SSE (mudah diganti di test)."""

    async def is_disconnected(self) -> bool:
        """True jika klien sudah memutus koneksi."""


async def aliran_sse(
    request: _KlienSSE,
    interval: float = INTERVAL_KEEPALIVE_DETIK,
    penyiar: Penyiar | None = None,
    snapshot: dict[str, Any] | None = None,
) -> AsyncIterator[str]:
    """Hasilkan aliran SSE: sapaan, lalu keepalive tiap `interval` detik.

    Dengan `penyiar`, kirim juga `snapshot` state awal dan pesan siaran. Berhenti saat klien putus.
    """
    yield ": terhubung\n\n"
    if penyiar is None:
        while not await request.is_disconnected():
            await asyncio.sleep(interval)
            if await request.is_disconnected():
                break
            yield ": keepalive\n\n"
        return

    antrean = penyiar.langgan()
    try:
        if snapshot is not None:
            yield format_sse("state", snapshot)
        while not await request.is_disconnected():
            try:
                yield await asyncio.wait_for(antrean.get(), timeout=interval)
            except TimeoutError:
                yield ": keepalive\n\n"
    finally:
        penyiar.berhenti(antrean)


@router.get("/", response_class=HTMLResponse)
async def halaman_utama(request: Request) -> HTMLResponse:
    """Tampilkan shell halaman kiosk operator beserta konfigurasi penangkap scanner."""
    s = request.app.state.settings
    konfig_scan = {
        "intervalMs": s.scan_interval_ms,
        "minPanjang": s.scan_min_length,
        "idleFlushMs": s.scan_idle_flush_ms,
    }
    return TEMPLATES.TemplateResponse(
        request, "index.html", {"judul": "Verifikasi Casing", "konfig_scan": konfig_scan}
    )


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Cek bahwa proses hidup; dipakai teknisi dan skrip pemantau."""
    return {"status": "ok"}


@router.get("/events")
async def events(request: Request) -> StreamingResponse:
    """Buka aliran SSE status siklus (snapshot state awal lalu perubahan state)."""
    state = request.app.state
    penyiar = getattr(state, "penyiar", None)
    siklus = getattr(state, "siklus", None)
    return StreamingResponse(
        aliran_sse(
            request,
            penyiar=penyiar,
            snapshot=siklus.ringkasan() if siklus is not None else None,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
