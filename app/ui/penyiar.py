"""Penyiar pub/sub untuk SSE; aman dipanggil dari thread pekerja maupun event loop."""

import asyncio
import json
import logging
import threading
from typing import Any

logger = logging.getLogger("app.ui.penyiar")

ANTREAN_MAKS = 100


def format_sse(event: str, data: dict[str, Any]) -> str:
    """Susun satu pesan SSE `event:` + `data:` (JSON)."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


class Penyiar:
    """Menyiarkan pesan SSE ke semua langganan; antrean penuh membuang pesan terlama."""

    def __init__(self, antrean_maks: int = ANTREAN_MAKS) -> None:
        """`antrean_maks` = kapasitas antrean per langganan."""
        self._antrean_maks = antrean_maks
        self._lock = threading.Lock()
        self._langganan: dict[asyncio.Queue[str], asyncio.AbstractEventLoop] = {}

    def langgan(self) -> asyncio.Queue[str]:
        """Buat antrean baru; harus dipanggil dari dalam event loop yang akan membacanya."""
        antrean: asyncio.Queue[str] = asyncio.Queue(maxsize=self._antrean_maks)
        with self._lock:
            self._langganan[antrean] = asyncio.get_running_loop()
        return antrean

    def berhenti(self, antrean: asyncio.Queue[str]) -> None:
        """Lepas langganan `antrean` (idempoten)."""
        with self._lock:
            self._langganan.pop(antrean, None)

    @property
    def jumlah_langganan(self) -> int:
        """Jumlah langganan aktif."""
        with self._lock:
            return len(self._langganan)

    def publish(self, event: str, data: dict[str, Any]) -> None:
        """Siarkan `event` dengan `data`; thread-safe (selalu lewat loop pemilik antrean)."""
        pesan = format_sse(event, data)
        with self._lock:
            sasaran = list(self._langganan.items())
        for antrean, loop in sasaran:
            try:
                loop.call_soon_threadsafe(self._taruh, antrean, pesan)
            except RuntimeError:  # loop sudah tertutup
                self.berhenti(antrean)

    @staticmethod
    def _taruh(antrean: asyncio.Queue[str], pesan: str) -> None:
        """Taruh pesan; bila penuh, buang yang terlama dan catat. Berjalan di loop pemilik."""
        if antrean.full():
            antrean.get_nowait()
            logger.warning("sse_antrean_penuh")
        antrean.put_nowait(pesan)
