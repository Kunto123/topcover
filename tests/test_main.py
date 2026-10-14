"""Test aplikasi FastAPI: route, aset statis, SSE, dan lifespan."""

import asyncio
import json
import logging

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.logging import NAMA_FILE_LOG
from app.ui.routes import aliran_sse


class _KlienPalsu:
    """Klien SSE palsu: terputus setelah `batas` pemeriksaan."""

    def __init__(self, batas: int) -> None:
        """Atur berapa kali is_disconnected mengembalikan False sebelum True."""
        self.sisa = batas

    async def is_disconnected(self) -> bool:
        """False sebanyak `batas` kali, lalu True."""
        if self.sisa <= 0:
            return True
        self.sisa -= 1
        return False


def test_healthz(client):
    """/healthz mengembalikan status ok."""
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_halaman_utama(client):
    """/ menampilkan shell kiosk berbahasa Indonesia dan memuat tema."""
    r = client.get("/")
    assert r.status_code == 200
    assert 'lang="id"' in r.text
    assert "/static/css/theme.css" in r.text
    assert "<input" not in r.text  # masukan scanner ditangkap global (CV-6), bukan kolom input


@pytest.mark.parametrize(
    "path", ["/static/css/theme.css", "/static/js/theme.js", "/static/js/events.js"]
)
def test_aset_statis(client, path):
    """Aset statis lokal tersedia (tanpa CDN)."""
    assert client.get(path).status_code == 200


async def _kumpulkan(klien: _KlienPalsu) -> list[str]:
    """Kumpulkan semua potongan dari aliran_sse sampai klien putus."""
    return [p async for p in aliran_sse(klien, interval=0)]


def test_aliran_sse_keepalive_lalu_berhenti():
    """Generator SSE mengirim sapaan + keepalive lalu berhenti saat klien putus."""
    potongan = asyncio.run(_kumpulkan(_KlienPalsu(batas=3)))
    assert potongan[0].startswith(": terhubung")
    assert ": keepalive\n\n" in potongan
    assert all(p.endswith("\n\n") for p in potongan)


def test_aliran_sse_klien_langsung_putus():
    """Klien yang sudah putus hanya menerima sapaan awal."""
    potongan = asyncio.run(_kumpulkan(_KlienPalsu(batas=0)))
    assert potongan == [": terhubung\n\n"]


def test_route_events_terdaftar(client):
    """Route /events terdaftar (dicek lewat OpenAPI, tanpa membuka aliran tak berujung)."""
    assert "/events" in client.app.openapi()["paths"]


def test_lifespan_menulis_app_start(settings, client):
    """Start aplikasi tercatat di file log dengan cycle_id '-'."""
    for handler in logging.getLogger().handlers:
        handler.flush()
    baris = [
        json.loads(b)
        for b in (settings.log_dir / NAMA_FILE_LOG).read_text(encoding="utf-8").splitlines()
    ]
    mulai = [b for b in baris if b["msg"] == "app_start"]
    assert mulai and mulai[0]["cycle_id"] == "-"


def test_host_non_loopback_tidak_bisa_membuat_settings():
    """Settings dengan host publik ditolak sebelum aplikasi dibuat."""
    with pytest.raises(ValidationError):
        Settings(host="0.0.0.0", _env_file=None)
