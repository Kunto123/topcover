"""Admin model: unggah (aliran mentah), status impor, daftar registri, aktifkan, dan rollback."""

import shutil
import threading
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.admin.deps import butuh_admin_api, butuh_admin_halaman, periksa_origin
from app.auth.model import Pengguna
from app.services.inference.tipe import ModelGagalDimuat
from app.services.model_import import (
    ImporGagal,
    ImporSibuk,
    PekerjaImpor,
    SiklusSibuk,
    UnggahTerlaluBesar,
    aktifkan_model,
    rollback_model,
    sanitasi_nama,
    simpan_aliran,
    validasi_versi,
)
from app.storage.local import registri_model
from app.ui.routes import TEMPLATES

router = APIRouter()
NAMA_MENU = "models"

Admin = Annotated[Pengguna, Depends(butuh_admin_api)]
_kunci = threading.Lock()


def _layanan(request: Request) -> tuple[Any, Any]:
    """Kolam DB dan mesin inferensi, atau 503."""
    st = request.app.state
    kolam, mesin = getattr(st, "db", None), getattr(st, "inferensi", None)
    if kolam is None or mesin is None:
        raise HTTPException(status_code=503, detail="Database lokal / mesin inferensi tidak aktif.")
    return kolam, mesin


def _pekerja(request: Request) -> PekerjaImpor:
    """Pekerja impor tunggal (dibuat saat pertama dipakai)."""
    st = request.app.state
    with _kunci:
        if getattr(st, "impor_pekerja", None) is None:
            kolam, mesin = _layanan(request)
            st.impor_pekerja = PekerjaImpor(kolam, mesin, st.siklus, st.settings)
        return st.impor_pekerja


def _ke_http(exc: Exception) -> HTTPException:
    """Petakan galat domain impor/aktivasi ke status HTTP."""
    if isinstance(exc, UnggahTerlaluBesar):
        return HTTPException(status_code=413, detail=str(exc))
    if isinstance(exc, ImporSibuk | SiklusSibuk):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(
        exc, registri_model.ModelTidakDitemukan | registri_model.TidakAdaModelUntukRollback
    ):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


@router.put("/api/models/unggah", dependencies=[Depends(periksa_origin)])
async def unggah(
    request: Request,
    admin: Admin,
    versi: str,
    nama_berkas: str,
    kelas: str = "",
    imgsz: int = 640,
    aktifkan: bool = False,
) -> JSONResponse:
    """Terima berkas model sebagai badan mentah, lalu mulai job impor (202 + id job)."""
    st = request.app.state
    try:
        versi = validasi_versi(versi)
        nama = sanitasi_nama(nama_berkas)
        if not 32 <= imgsz <= 2048:
            raise ImporGagal("imgsz harus 32-2048.")
        pekerja = _pekerja(request)
        if st.siklus.state.value not in ("WAIT_DATAPART", "DONE"):
            raise SiklusSibuk("Siklus pemeriksaan sedang berjalan; coba lagi setelah selesai.")
        batas = st.settings.model_upload_maks_mb * 1024 * 1024
        panjang = request.headers.get("content-length")
        if panjang is not None and panjang.isdigit() and int(panjang) > batas:
            raise UnggahTerlaluBesar(
                f"Berkas melebihi batas {st.settings.model_upload_maks_mb} MB."
            )
    except ImporGagal as exc:
        raise _ke_http(exc) from exc
    folder = pekerja.staging_dir / f"unggah-{uuid.uuid4().hex[:10]}"
    try:
        await simpan_aliran(request.stream(), folder / nama, batas)
        daftar_kelas = [k.strip() for k in kelas.split(",") if k.strip()] or None
        job = pekerja.ajukan(
            folder / nama,
            versi,
            kelas_manual=daftar_kelas,
            imgsz=imgsz,
            aktifkan=aktifkan,
            oleh=admin.username,
        )
    except ImporGagal as exc:
        shutil.rmtree(folder, ignore_errors=True)
        raise _ke_http(exc) from exc
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    return JSONResponse({"job_id": job.id}, status_code=202)


@router.get("/api/models/jobs/{job_id}")
def status_job(job_id: str, request: Request, _: Admin) -> dict[str, Any]:
    """Status job impor (`antri..selesai|gagal`)."""
    job = _pekerja(request).status(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job tidak ditemukan.")
    return job.ringkas()


@router.get("/api/models")
def daftar_model(request: Request, _: Admin) -> dict[str, Any]:
    """Daftar model registri (terbaru dulu) dan status mesin inferensi."""
    kolam, mesin = _layanan(request)
    with kolam.connection() as conn:
        baris = registri_model.daftar(conn)
    return {
        "model": [
            {
                "id": b["id"],
                "versi": b["versi"],
                "status": b["status"],
                "kelas": (b["metadata"] or {}).get("nama_kelas"),
                "dibuat_pada": b["dibuat_pada"].isoformat(),
                "diaktifkan_pada": b["diaktifkan_pada"].isoformat()
                if b["diaktifkan_pada"]
                else None,
            }
            for b in baris
        ],
        "mesin": mesin.status(),
    }


@router.post("/api/models/{model_id}/aktifkan", dependencies=[Depends(periksa_origin)])
def aktifkan(model_id: int, request: Request, admin: Admin) -> dict[str, Any]:
    """Aktifkan model tanpa restart; gagal muat -> registri dikembalikan (422)."""
    kolam, mesin = _layanan(request)
    try:
        versi = aktifkan_model(kolam, mesin, request.app.state.siklus, model_id, admin.username)
    except (ImporGagal, ModelGagalDimuat, registri_model.ModelTidakDitemukan) as exc:
        raise _ke_http(exc) from exc
    return {"versi": versi}


@router.post("/api/models/rollback", dependencies=[Depends(periksa_origin)])
def rollback(request: Request, admin: Admin) -> dict[str, Any]:
    """Kembalikan model arsip terakhir yang aktif tanpa restart."""
    kolam, mesin = _layanan(request)
    try:
        versi = rollback_model(kolam, mesin, request.app.state.siklus, admin.username)
    except (
        ImporGagal,
        ModelGagalDimuat,
        registri_model.TidakAdaModelUntukRollback,
    ) as exc:
        raise _ke_http(exc) from exc
    return {"versi": versi}


@router.get("/models", response_class=HTMLResponse)
def halaman_model(
    request: Request, pengguna: Annotated[Pengguna, Depends(butuh_admin_halaman)]
) -> HTMLResponse:
    """Halaman admin model."""
    from app.admin.routes import MENU

    return TEMPLATES.TemplateResponse(
        request,
        "admin/models.html",
        {"judul": "Model — Admin", "menu": MENU, "konfig_scan": {}, "pengguna": pengguna},
    )
