# Verifikasi Casing

Operator scan datapart → tekan tombol → kamera mengambil gambar 1 box (6 part) → model YOLO11 kiri/kanan +
pengukuran warna → **MATCH / NOT_MATCH** → simpan (lokal + pabrik) → print hanya bila MATCH.
Satu aplikasi lokal (FastAPI) di PC station; UI web kiosk di `127.0.0.1`. Target siklus ≤ 10 detik.

## Status sistem
Seluruh alur sudah tersambung dan teruji dengan perangkat tiruan (kamera, model, pabrik, printer):
scan/RFID, login, kamera + preview, inferensi OpenVINO, aturan box, simpan atomik lokal↔pabrik, gerbang print,
admin (model, warna, pengaturan, audit SPV), pembersihan gambar, skrip spike.
**Belum terbukti dengan perangkat nyata**: format output model YOLO11, ruang warna/toleransi, latensi di PC target,
pemindai asli, skema/hash database pabrik, printer asli. Nilai sementara (placeholder) ada di `docs/env.md`
dan `docs/runbook.md` bagian 6.

## Setup
Prasyarat: Python 3.11, PostgreSQL 15+. Venv proyek: `.cover`.
```powershell
.cover\Scripts\python.exe -m pip install -e ".[dev]"
copy .env.example .env
# isi CASING_LOCAL_DATABASE_URL; buat admin pertama:
.cover\Scripts\python.exe -m app.auth buat-admin admin1
```
Mode dev tanpa login/model/pabrik: `CASING_AUTH_WAJIB=false CASING_DEBUG=true CASING_INFERENCE_WAJIB=false
CASING_FACTORY_MODE=tiruan` (hasil TIDAK dikirim ke pabrik).

## Jalankan
```powershell
.cover\Scripts\python.exe -m app          # http://127.0.0.1:8000  (kiosk)  ·  /admin  ·  /healthz
```
Log JSON ke konsol dan `data/logs/casing.log` (tiap baris membawa `cycle_id`).
Daftarkan model: `/admin/models` atau `python -m app.services.inference daftarkan ...` (lihat `docs/inferensi.md`).

## Test, lint, dokumentasi
```powershell
$env:CASING_TEST_DATABASE_URL = "postgresql://postgres@127.0.0.1:5432/postgres"   # akun boleh CREATE DATABASE
.cover\Scripts\python.exe -m pytest -q            # tanpa env di atas, test PostgreSQL dilewati
.cover\Scripts\python.exe -m ruff check app tools tests
node --test "tests/js/*.test.mjs"
.cover\Scripts\python.exe -m tools.check_docstrings app tools     # docstring Indonesia 1-2 baris
.cover\Scripts\python.exe -m tools.dump_env > docs\env.md          # setelah mengubah Settings
```

## Peta dokumen
| Dokumen | Isi |
|---|---|
| `docs/gambaran-sistem.md` | penjelasan menyeluruh: arsitektur, siklus, aturan, data, batasan |
| `docs/runbook.md` | troubleshoot: kode alasan, status, penelusuran `cycle_id`, prosedur |
| `docs/env.md` | seluruh variabel `CASING_*` (dibangkitkan) |
| `docs/siklus.md` | alur end-to-end dan status hasil |
| `docs/auth.md`, `docs/pabrik-pemetaan.md` | login, database pabrik |
| `docs/inferensi.md`, `docs/model-impor.md` | model OpenVINO, impor admin |
| `docs/kamera.md`, `docs/retensi.md`, `docs/audit-spv.md` | kamera, pembersihan gambar, audit |
| `docs/spike-warna.md`, `spike-inferensi.md`, `spike-kamera.md`, `spike-c-protokol.md` | cara menjalankan spike |
| `docs/konvensi.md` | konvensi kode |
| `.claude/plans/INDEX.md` | status plan dan keputusan terbuka |
