-- Akun login lokal (CV-5). Hanya peran admin; hash password scrypt. Jangan diedit setelah diterapkan.
CREATE TABLE akun_lokal (
    id             serial PRIMARY KEY,
    username       text        NOT NULL,
    password_hash  text        NOT NULL,
    peran          text        NOT NULL DEFAULT 'admin' CHECK (peran = 'admin'),
    aktif          boolean     NOT NULL DEFAULT true,
    dibuat_pada    timestamptz NOT NULL DEFAULT now(),
    diubah_pada    timestamptz NOT NULL DEFAULT now()
);
-- Username unik tanpa membedakan huruf besar/kecil.
CREATE UNIQUE INDEX akun_lokal_username_idx ON akun_lokal (lower(username));
