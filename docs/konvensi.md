# Konvensi Kode — Verifikasi Casing

## Struktur modul (satu tanggung jawab per paket)

| Paket | Tanggung jawab | Tiket |
|---|---|---|
| `app/core` | konfigurasi, log, kode alasan, state siklus | CV-1 |
| `app/domain` | aturan box & pengukuran warna (fungsi murni) | CV-2, CV-6 |
| `app/storage` | database lokal & adapter database pabrik | CV-3, CV-4 |
| `app/services/camera` | kamera & preview | CV-7 |
| `app/services/inference` | inferensi OpenVINO & registri model | CV-8 |
| `app/services/printing` | `PrintPort` & simulasi | CV-11 |
| `app/auth` | login, peran, audit | CV-5 |
| `app/api` | endpoint siklus | CV-6, CV-12 |
| `app/admin` | layar admin | CV-9, CV-10, CV-14 |
| `app/workers` | pekerjaan berkala | CV-13 |
| `app/ui` | halaman kiosk, aset statis, SSE | CV-1 |

Satu kegagalan harus menunjuk satu paket. Jangan menaruh logika paket A di paket B.

## Docstring

Setiap function, class, dan parameter publik punya docstring **bahasa Indonesia, 1–2 baris**.
Parameter dijelaskan di baris yang sama atau baris kedua.

```python
def tulis_log(pesan: str, cycle_id: str | None = None) -> None:
    """Tulis satu baris log JSON. `pesan` teks ringkas; `cycle_id` kosong = pakai konteks aktif."""
```

Pengecekan otomatis dibuat di CV-15.

## Nilai enum = kontrak

Nilai string `ReasonCode`, `Verdict`, dan `CycleState` masuk ke database dan log. Setelah dipakai,
**jangan diganti**. Menambah kode alasan baru:

1. Tambah anggota di `app/core/reasons.py`.
2. Tambah deskripsi di `REASON_DESCRIPTIONS`.
3. Tambah/ubah test di `tests/core/test_reasons_states.py`.

`GAGAL_PUSH` adalah kegagalan sistem, bukan alasan verdict; rule engine tidak boleh memakainya.

## Log dan `cycle_id`

Log berupa satu baris JSON dengan kunci `ts`, `level`, `logger`, `cycle_id`, `msg` (+ `extra`).
Di luar siklus, `cycle_id` bernilai `"-"`.

```python
from app.core.logging import bind_cycle_id, new_cycle_id

with bind_cycle_id(new_cycle_id()):
    logger.info("capture_mulai")
```

`ContextVar` **tidak** merambat ke thread buatan manual. Pakai `asyncio.to_thread` atau
`contextvars.copy_context().run(fungsi)` saat memindahkan kerja ke thread pekerja (CV-7, CV-8).
Jangan mencatat kredensial.

## Test

`pytest -q` dari root repo, memakai venv `.cover` (Python 3.11). Test harus hermetik: `log_dir` di
`tmp_path`, tanpa jaringan, kamera, atau database. Jangan membuka `/events` lewat `TestClient`
(aliran tak berujung); uji generator `aliran_sse` langsung.
