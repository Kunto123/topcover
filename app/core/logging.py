"""Log terstruktur JSON; setiap baris membawa `cycle_id` dari konteks aktif.

Catatan: `ContextVar` tidak merambat ke thread buatan manual; pakai `asyncio.to_thread`
atau `contextvars.copy_context().run(...)` agar `cycle_id` ikut terbawa.
"""

import json
import logging
import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler

from app.core.config import Settings

CYCLE_ID_KOSONG = "-"
NAMA_FILE_LOG = "casing.log"
_HANDLER_TAG = "_casing_handler"

_cycle_id: ContextVar[str | None] = ContextVar("cycle_id", default=None)

# Atribut bawaan LogRecord; selainnya dianggap `extra` dari pemanggil.
_ATRIBUT_BAWAAN = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys()) | {
    "message",
    "asctime",
    "cycle_id",
}


def new_cycle_id() -> str:
    """Buat `cycle_id` baru (uuid4 hex) untuk satu siklus scan sampai print."""
    return uuid.uuid4().hex


def get_cycle_id() -> str | None:
    """Ambil `cycle_id` pada konteks aktif, atau None jika tidak ada siklus."""
    return _cycle_id.get()


@contextmanager
def bind_cycle_id(cycle_id: str) -> Iterator[str]:
    """Pasang `cycle_id` selama blok `with`; konteks sebelumnya dipulihkan saat keluar."""
    token = _cycle_id.set(cycle_id)
    try:
        yield cycle_id
    finally:
        _cycle_id.reset(token)


class CycleIdFilter(logging.Filter):
    """Suntik `cycle_id` konteks aktif ke setiap record sebelum diformat."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Isi `record.cycle_id` (atau '-') dan loloskan record."""
        record.cycle_id = get_cycle_id() or CYCLE_ID_KOSONG
        return True


class JsonFormatter(logging.Formatter):
    """Format satu record menjadi satu baris JSON dengan kunci tetap + `extra` pemanggil."""

    def format(self, record: logging.LogRecord) -> str:
        """Kembalikan baris JSON: ts, level, logger, cycle_id, msg, dan extra."""
        data = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "cycle_id": getattr(record, "cycle_id", None) or get_cycle_id() or CYCLE_ID_KOSONG,
            "msg": record.getMessage(),
        }
        for kunci, nilai in record.__dict__.items():
            if kunci not in _ATRIBUT_BAWAAN and not kunci.startswith("_"):
                data[kunci] = nilai
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return json.dumps(data, ensure_ascii=False, default=str)


def configure_logging(settings: Settings) -> None:
    """Pasang handler konsol dan file berputar ke root logger; aman dipanggil berulang."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, _HANDLER_TAG, False):
            root.removeHandler(handler)
            handler.close()

    try:
        settings.log_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RuntimeError(f"Tidak bisa membuat direktori log {settings.log_dir}: {exc}") from exc

    formatter = JsonFormatter()
    handlers: list[logging.Handler] = [
        logging.StreamHandler(sys.stderr),
        RotatingFileHandler(
            settings.log_dir / NAMA_FILE_LOG,
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        ),
    ]
    for handler in handlers:
        handler.setFormatter(formatter)
        handler.addFilter(CycleIdFilter())
        setattr(handler, _HANDLER_TAG, True)
        root.addHandler(handler)
    root.setLevel(settings.log_level.upper())
