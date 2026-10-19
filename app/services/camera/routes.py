"""Route layanan kamera: preview MJPEG dan status (CV-7)."""

import dataclasses
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from app.services.camera.mjpeg import aliran_mjpeg

router = APIRouter()


@router.get("/api/camera/status")
async def status_kamera(request: Request) -> dict[str, Any]:
    """Status kamera sebagai JSON; `{"aktif": false}` bila kamera dimatikan."""
    kamera = getattr(request.app.state, "kamera", None)
    if kamera is None:
        return {"aktif": False}
    return {"aktif": True, **dataclasses.asdict(kamera.status())}


@router.get("/camera/stream", response_model=None)
async def stream_kamera(request: Request) -> Response:
    """Alirkan preview MJPEG; 503 bila kamera dimatikan, 429 bila klien preview sudah penuh."""
    state = request.app.state
    kamera = getattr(state, "kamera", None)
    if kamera is None:
        return JSONResponse({"pesan": "Kamera dimatikan atau belum dimulai."}, status_code=503)
    semafor = state.mjpeg_sem
    if semafor.locked():
        return JSONResponse({"pesan": "Terlalu banyak klien preview."}, status_code=429)
    await semafor.acquire()
    s = state.settings

    async def isi() -> AsyncIterator[bytes]:
        """Alirkan MJPEG lalu lepaskan slot klien."""
        try:
            async for bagian in aliran_mjpeg(kamera, request, s.preview_fps, s.preview_width):
                yield bagian
        finally:
            semafor.release()

    return StreamingResponse(
        isi(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
