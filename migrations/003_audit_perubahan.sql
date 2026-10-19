-- Audit perubahan umum (CV-0c): siapa mengubah apa dan kapan (varian, konfigurasi, model).
CREATE TABLE audit_perubahan (
    id              bigserial PRIMARY KEY,
    waktu           timestamptz NOT NULL DEFAULT now(),
    oleh            text        NOT NULL,
    aksi            text        NOT NULL,
    objek           text        NOT NULL,
    detail          jsonb       NOT NULL DEFAULT '{}'::jsonb,
    versi_sebelum   integer,
    versi_sesudah   integer
);
CREATE INDEX audit_perubahan_waktu_idx ON audit_perubahan (waktu);
CREATE INDEX audit_perubahan_objek_waktu_idx ON audit_perubahan (objek, waktu);
