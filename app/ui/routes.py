"""Route halaman kiosk, health check, dan aliran SSE."""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Protocol

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

UI_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(UI_DIR / "templates"))
INTERVAL_KEEPALIVE_DETIK = 15.0

router = APIRouter()


class _KlienSSE(Protocol):
    """Bentuk minimal klien yang dibutuhkan aliran SSE (mudah diganti di test)."""

    async def is_disconnected(self) -> bool:
        """True jika klien sudah memutus koneksi."""


async def aliran_sse(
    request: _KlienSSE, interval: float = INTERVAL_KEEPALIVE_DETIK
) -> AsyncIterator[str]:
    """Hasilkan komentar SSE: sapaan awal, lalu keepalive tiap `interval` detik.

    Berhenti saat `request` melaporkan klien sudah putus.
    """
    yield ": terhubung\n\n"
    while not await request.is_disconnected():
        await asyncio.sleep(interval)
        if await request.is_disconnected():
            break
        yield ": keepalive\n\n"


@router.get("/", response_class=HTMLResponse)
async def halaman_utama(request: Request) -> HTMLResponse:
    """Tampilkan shell halaman kiosk operator."""
    return TEMPLATES.TemplateResponse(request, "index.html", {"judul": "Verifikasi Casing"})


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Cek bahwa proses hidup; dipakai teknisi dan skrip pemantau."""
    return {"status": "ok"}


@router.get("/events")
async def events(request: Request) -> StreamingResponse:
    """Buka aliran SSE status siklus (saat ini hanya keepalive; diisi CV-6/CV-12)."""
    return StreamingResponse(
        aliran_sse(request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
