"""Fixture bersama: settings hermetik, klien test, dan pemulihan logging."""

import logging

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path) -> Settings:
    """Settings dengan log_dir di direktori sementara dan tanpa membaca .env."""
    return Settings(log_dir=tmp_path / "logs", _env_file=None)


@pytest.fixture
def client(settings):
    """TestClient untuk aplikasi yang dibuat dari `settings`."""
    with TestClient(create_app(settings)) as c:
        yield c


@pytest.fixture(autouse=True)
def _pulihkan_logging():
    """Kembalikan handler root logger setelah tiap test agar file log sementara dilepas."""
    root = logging.getLogger()
    handler_awal = list(root.handlers)
    level_awal = root.level
    yield
    for handler in list(root.handlers):
        if handler not in handler_awal:
            root.removeHandler(handler)
            handler.close()
    root.setLevel(level_awal)
