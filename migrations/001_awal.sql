-- Skema awal database lokal (CV-3). Dijalankan sekali; jangan diedit setelah diterapkan.
-- Kolom relasional hanya untuk yang difilter/dihitung; detail fleksibel disimpan sebagai JSONB.

-- Hasil pemeriksaan satu box. Hanya ada baris bila push ke pabrik berhasil (keputusan produk).
CREATE TABLE hasil_pemeriksaan (
    id                  bigserial PRIMARY KEY,
    cycle_id            text        NOT NULL UNIQUE,
    datapart            text        NOT NULL,
    verdict             text        NOT NULL CHECK (verdict IN ('match', 'not_match')),
    reason_code         text,
    operator            text        NOT NULL,
    waktu_scan          timestamptz NOT NULL,
    waktu_selesai       timestamptz NOT NULL DEFAULT now(),
    durasi_total_ms     integer     CHECK (durasi_total_ms >= 0),
    tahap_ms            jsonb       NOT NULL DEFAULT '{}'::jsonb,
    path_gambar         text,
    gambar_dibersihkan  boolean     NOT NULL DEFAULT false,
    detail_part         jsonb       NOT NULL DEFAULT '[]'::jsonb,
    -- MATCH tanpa alasan; NOT_MATCH wajib beralasan. Nilai reason_code tidak dibatasi di DB
    -- (sumber kebenaran = enum aplikasi, agar tidak terjadi drift).
    CHECK ((verdict = 'match' AND reason_code IS NULL)
        OR (verdict = 'not_match' AND reason_code IS NOT NULL))
);
CREATE INDEX hasil_waktu_selesai_idx ON hasil_pemeriksaan (waktu_selesai);
CREATE INDEX hasil_verdict_waktu_idx ON hasil_pemeriksaan (verdict, waktu_selesai);
CREATE INDEX hasil_datapart_idx ON hasil_pemeriksaan (datapart);
-- Untuk pembersihan gambar (CV-13): hanya baris yang masih punya file.
CREATE INDEX hasil_gambar_belum_dibersihkan_idx ON hasil_pemeriksaan (waktu_selesai)
    WHERE gambar_dibersihkan = false AND path_gambar IS NOT NULL;

-- Varian warna referensi (dikelola admin, tanpa retrain model).
CREATE TABLE varian_warna (
    id           serial PRIMARY KEY,
    nama         text        NOT NULL UNIQUE,
    spesifikasi  jsonb       NOT NULL,
    aktif        boolean     NOT NULL DEFAULT true,
    versi        integer     NOT NULL DEFAULT 1,
    diubah_pada  timestamptz NOT NULL DEFAULT now(),
    diubah_oleh  text
);

-- Registri model. Paling banyak satu baris berstatus 'aktif'.
CREATE TABLE registri_model (
    id               serial PRIMARY KEY,
    versi            text        NOT NULL UNIQUE,
    path             text        NOT NULL,
    status           text        NOT NULL CHECK (status IN ('aktif', 'arsip', 'nonaktif')),
    metadata         jsonb       NOT NULL DEFAULT '{}'::jsonb,
    dibuat_pada      timestamptz NOT NULL DEFAULT now(),
    diaktifkan_pada  timestamptz
);
-- Indeks unik parsial pada ekspresi konstan: dua baris 'aktif' tidak mungkin ada.
CREATE UNIQUE INDEX registri_model_satu_aktif ON registri_model ((true)) WHERE status = 'aktif';

-- Konfigurasi aplikasi berversi: perubahan menambah baris, tidak menimpa.
CREATE TABLE konfigurasi_aplikasi (
    versi        integer     PRIMARY KEY,
    data         jsonb       NOT NULL,
    dibuat_pada  timestamptz NOT NULL DEFAULT now(),
    dibuat_oleh  text
);

-- Audit autentikasi (sumber: lokal atau pabrik).
CREATE TABLE audit_auth (
    id        bigserial PRIMARY KEY,
    waktu     timestamptz NOT NULL DEFAULT now(),
    username  text,
    sumber    text        NOT NULL CHECK (sumber IN ('lokal', 'pabrik')),
    peran     text,
    hasil     text        NOT NULL CHECK (hasil IN ('sukses', 'gagal')),
    alasan    text,
    detail    jsonb       NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX audit_auth_waktu_idx ON audit_auth (waktu);
CREATE INDEX audit_auth_username_waktu_idx ON audit_auth (username, waktu);
