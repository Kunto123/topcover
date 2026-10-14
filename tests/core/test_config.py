"""Test konfigurasi aplikasi."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings


def test_default_aman():
    """Default: loopback, port 8000, INFO, tanpa debug."""
    s = Settings(_env_file=None)
    assert s.host == "127.0.0.1"
    assert s.port == 8000
    assert s.log_level == "INFO"
    assert s.log_dir == Path("data/logs")
    assert s.debug is False


def test_override_dari_environment(monkeypatch):
    """Variabel CASING_* menimpa default."""
    monkeypatch.setenv("CASING_PORT", "9000")
    monkeypatch.setenv("CASING_LOG_LEVEL", "DEBUG")
    s = Settings(_env_file=None)
    assert s.port == 9000
    assert s.log_level == "DEBUG"


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.5", "example.com", ""])
def test_host_non_loopback_ditolak(host):
    """Web UI hanya boleh mendengarkan loopback."""
    with pytest.raises(ValidationError):
        Settings(host=host, _env_file=None)


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_host_loopback_diterima(host):
    """Alamat loopback yang sah diterima."""
    assert Settings(host=host, _env_file=None).host == host


def test_kunci_asing_di_env_file_diabaikan(tmp_path):
    """Kunci tak dikenal di .env tidak menyebabkan error."""
    env = tmp_path / ".env"
    env.write_text("QC_SUITE_SECRET_KEY=x\nCASING_PORT=8123\n", encoding="utf-8")
    s = Settings(_env_file=env)
    assert s.port == 8123


def test_get_settings_di_cache():
    """get_settings mengembalikan objek yang sama sampai cache dibersihkan."""
    get_settings.cache_clear()
    assert get_settings() is get_settings()
    get_settings.cache_clear()
