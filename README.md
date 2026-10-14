# Verifikasi Casing

Scan datapart → cek kamera → MATCH / NOT_MATCH → simpan → print (hanya MATCH).
Satu aplikasi lokal (FastAPI) di PC station, UI web kiosk di `127.0.0.1`.

Dokumen: `.claude/casing-verification.prd.md` (maksud), `.claude/casing-verification.architecture.md`
(keputusan), `docs/tickets/casing-verification.md` (tiket), `docs/konvensi.md` (konvensi kode).

> Status: baru fondasi (CV-1). Kamera, inferensi, database, auth, dan printer menyusul di tiket lain.

## Setup

Prasyarat: Python 3.11. Venv proyek: `.cover`.

```powershell
.cover\Scripts\python.exe -m pip install -e ".[dev]"
copy .env.example .env   # opsional
```

## Jalankan

```powershell
.cover\Scripts\python.exe -m app
```

Buka <http://127.0.0.1:8000>. Cek hidup: <http://127.0.0.1:8000/healthz>.
Log JSON ke konsol dan `data/logs/casing.log`.

## Test dan lint

```powershell
.cover\Scripts\python.exe -m pytest -q
.cover\Scripts\python.exe -m ruff check app tests
.cover\Scripts\python.exe -m ruff format --check app tests
```

## Konfigurasi

Variabel `CASING_*` (lihat `.env.example`). `CASING_HOST` hanya boleh loopback.
