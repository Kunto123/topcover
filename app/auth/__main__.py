"""CLI akun admin lokal: `python -m app.auth buat-admin|ganti-password|nonaktifkan|aktifkan|daftar`.

Password hanya dibaca interaktif (getpass), tidak pernah lewat argumen atau environment.
"""

import argparse
import getpass
import os
import sys
from collections.abc import Callable, Sequence

from app.auth.hash import PasswordLemah, hash_password, validasi_kekuatan
from app.storage.local import akun_lokal, audit_auth
from app.storage.local.db import DatabaseTidakTersedia, buka_koneksi
from app.storage.local.migrasi import terapkan_migrasi


def _baca_password_interaktif() -> str:
    """Minta password dua kali lewat getpass; tidak sama -> ValueError."""
    satu = getpass.getpass("Password baru: ")
    dua = getpass.getpass("Ulangi password: ")
    if satu != dua:
        raise ValueError("Kedua password tidak sama.")
    return satu


def _audit(conn, username: str, aksi: str) -> None:
    """Catat aksi CLI ke audit_auth (tanpa password)."""
    audit_auth.catat(
        conn, username=username, sumber="lokal", hasil="sukses", peran="admin", alasan=f"cli:{aksi}"
    )


def jalankan(
    argv: Sequence[str],
    *,
    dsn: str | None = None,
    baca_password: Callable[[], str] = _baca_password_interaktif,
    cetak: Callable[[str], None] = print,
) -> int:
    """Jalankan perintah CLI; kembalikan kode keluar (0 sukses)."""
    parser = argparse.ArgumentParser(prog="python -m app.auth", description=__doc__)
    sub = parser.add_subparsers(dest="perintah", required=True)
    for nama in ("buat-admin", "ganti-password", "nonaktifkan", "aktifkan"):
        sub.add_parser(nama).add_argument("username")
    sub.add_parser("daftar")
    args = parser.parse_args(list(argv))

    dsn = dsn or os.environ.get("CASING_LOCAL_DATABASE_URL")
    if not dsn:
        cetak("CASING_LOCAL_DATABASE_URL belum diisi.")
        return 2
    try:
        conn = buka_koneksi(dsn)
    except DatabaseTidakTersedia as exc:
        cetak(str(exc))
        return 2
    try:
        conn.autocommit = True
        terapkan_migrasi(conn)
        if args.perintah == "daftar":
            for a in akun_lokal.daftar(conn):
                cetak(f"{a['username']}\t{a['peran']}\t{'aktif' if a['aktif'] else 'nonaktif'}")
            return 0
        username = args.username.strip()
        if args.perintah in ("buat-admin", "ganti-password"):
            if args.perintah == "ganti-password" and akun_lokal.ambil(conn, username) is None:
                cetak(f"Akun {username!r} tidak ada.")
                return 1
            try:
                password = baca_password()
                validasi_kekuatan(password, username)
            except (PasswordLemah, ValueError) as exc:
                cetak(str(exc))
                return 1
            if args.perintah == "buat-admin":
                try:
                    akun_lokal.buat(conn, username, hash_password(password))
                except (akun_lokal.AkunSudahAda, ValueError) as exc:
                    cetak(str(exc))
                    return 1
            else:
                akun_lokal.ganti_hash(conn, username, hash_password(password))
        else:
            if not akun_lokal.set_aktif(conn, username, args.perintah == "aktifkan"):
                cetak(f"Akun {username!r} tidak ada.")
                return 1
        _audit(conn, username, args.perintah)
        cetak(f"OK: {args.perintah} {username}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(jalankan(sys.argv[1:]))
