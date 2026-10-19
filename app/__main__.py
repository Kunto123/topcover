"""Jalankan aplikasi: `python -m app` (hanya mendengarkan loopback)."""

import uvicorn

from app.core.config import get_settings
from app.main import create_app


def main() -> None:
    """Start uvicorn pada host/port dari Settings.

    `log_config=None` agar konfigurasi log JSON kita tidak tertimpa uvicorn.
    """
    settings = get_settings()
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_config=None,
        # SSE (/events) dan MJPEG (/camera/stream) tidak pernah selesai sendiri; tanpa batas ini
        # Ctrl+C menunggu browser menutup tab.
        timeout_graceful_shutdown=3,
    )


if __name__ == "__main__":
    main()
