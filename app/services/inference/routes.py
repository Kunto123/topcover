"""Route status inferensi."""

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/inference", tags=["inferensi"])


@router.get("/status")
async def status(request: Request) -> dict:
    """Status model: siap, versi, device, galat, ukuran input, latensi terakhir."""
    mesin = getattr(request.app.state, "inferensi", None)
    if mesin is None:
        return {"siap": False, "galat": "Mesin inferensi belum dibuat."}
    return mesin.status()
