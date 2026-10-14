"""Test log JSON dan konteks cycle_id."""

import json
import logging

import pytest

from app.core.logging import (
    NAMA_FILE_LOG,
    bind_cycle_id,
    configure_logging,
    get_cycle_id,
    new_cycle_id,
)

KUNCI_WAJIB = {"ts", "level", "logger", "cycle_id", "msg"}


def _baca_log(settings) -> list[dict]:
    """Baca semua baris JSON dari file log."""
    for handler in logging.getLogger().handlers:
        handler.flush()
    teks = (settings.log_dir / NAMA_FILE_LOG).read_text(encoding="utf-8")
    return [json.loads(baris) for baris in teks.splitlines() if baris.strip()]


def test_baris_json_punya_kunci_wajib_dan_cycle_id_kosong(settings):
    """Di luar siklus, cycle_id berisi '-'."""
    configure_logging(settings)
    logging.getLogger("uji").info("halo")
    baris = _baca_log(settings)[-1]
    assert KUNCI_WAJIB <= set(baris)
    assert baris["cycle_id"] == "-"
    assert baris["msg"] == "halo"


def test_cycle_id_terisi_di_dalam_bind(settings):
    """Di dalam bind_cycle_id, baris log membawa cycle_id tersebut."""
    configure_logging(settings)
    with bind_cycle_id("abc"):
        logging.getLogger("uji").info("dalam")
    logging.getLogger("uji").info("luar")
    dalam, luar = _baca_log(settings)[-2:]
    assert dalam["cycle_id"] == "abc"
    assert luar["cycle_id"] == "-"


def test_bind_bersarang_kembali_ke_nilai_luar():
    """bind di dalam bind memulihkan nilai luar saat keluar."""
    with bind_cycle_id("luar"):
        with bind_cycle_id("dalam"):
            assert get_cycle_id() == "dalam"
        assert get_cycle_id() == "luar"
    assert get_cycle_id() is None


def test_bind_pulih_saat_exception():
    """Exception di dalam blok tetap mereset konteks."""
    with pytest.raises(ValueError), bind_cycle_id("x"):
        raise ValueError("gagal")
    assert get_cycle_id() is None


def test_configure_logging_idempoten(settings):
    """Dua kali configure_logging tidak menggandakan handler kita."""
    configure_logging(settings)
    jumlah = len(logging.getLogger().handlers)
    configure_logging(settings)
    assert len(logging.getLogger().handlers) == jumlah


def test_non_ascii_dan_extra_tak_serializable_tidak_melempar(settings):
    """Pesan non-ASCII dan extra yang bukan JSON tidak membuat logging gagal."""
    configure_logging(settings)
    logging.getLogger("uji").info("Kiri/Kanan — tutup ✓", extra={"obj": object(), "n": 3})
    baris = _baca_log(settings)[-1]
    assert baris["msg"] == "Kiri/Kanan — tutup ✓"
    assert baris["n"] == 3
    assert isinstance(baris["obj"], str)


def test_exception_dicatat(settings):
    """logger.exception menyertakan kunci exc."""
    configure_logging(settings)
    try:
        raise RuntimeError("meledak")
    except RuntimeError:
        logging.getLogger("uji").exception("error")
    assert "meledak" in _baca_log(settings)[-1]["exc"]


def test_direktori_log_tidak_bisa_dibuat(settings, tmp_path):
    """log_dir yang bertabrakan dengan file menghasilkan RuntimeError berpesan jelas."""
    file_biasa = tmp_path / "file"
    file_biasa.write_text("x")
    settings.log_dir = file_biasa / "logs"
    with pytest.raises(RuntimeError, match="direktori log"):
        configure_logging(settings)


def test_new_cycle_id_unik():
    """Dua cycle_id baru tidak sama."""
    assert new_cycle_id() != new_cycle_id()
