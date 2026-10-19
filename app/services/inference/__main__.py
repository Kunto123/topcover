"""CLI registri model (jembatan sampai CV-9): daftarkan, aktifkan, rollback, status.

Hanya mengubah registri di database. Aplikasi yang sedang berjalan perlu di-restart agar
memuat model aktif yang baru. Tidak mengonversi format (itu pekerjaan CV-9).
"""

import argparse
import os
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from app.services.inference.mesin import petakan_kelas
from app.services.inference.pelari import cari_xml
from app.services.inference.tipe import ModelGagalDimuat
from app.storage.local import registri_model
from app.storage.local.db import DatabaseTidakTersedia, buka_koneksi
from app.storage.local.migrasi import terapkan_migrasi
from app.storage.local.skema import MetadataModel


def jalankan(
    argv: Sequence[str], *, dsn: str | None = None, cetak: Callable[[str], None] = print
) -> int:
    """Jalankan perintah CLI; kembalikan kode keluar (0 sukses)."""
    parser = argparse.ArgumentParser(prog="python -m app.services.inference", description=__doc__)
    sub = parser.add_subparsers(dest="perintah", required=True)
    d = sub.add_parser("daftarkan")
    d.add_argument("--versi", required=True)
    d.add_argument("--path", required=True)
    d.add_argument("--kelas", nargs="+", required=True)
    d.add_argument("--aktifkan", action="store_true")
    sub.add_parser("aktifkan").add_argument("id", type=int)
    sub.add_parser("rollback")
    sub.add_parser("status")
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
        if args.perintah == "daftarkan":
            try:
                cari_xml(Path(args.path))
                petakan_kelas(args.kelas)
                meta = MetadataModel(nama_kelas=args.kelas, format_asal="openvino")
            except (ModelGagalDimuat, ValueError) as exc:
                cetak(f"Ditolak: {exc}")
                return 1
            model_id = registri_model.daftarkan(
                conn,
                args.versi,
                str(Path(args.path).resolve()),
                meta,
                "aktif" if args.aktifkan else "nonaktif",
            )
            cetak(f"Terdaftar id={model_id} versi={args.versi}")
        elif args.perintah == "aktifkan":
            registri_model.aktifkan(conn, args.id)
            cetak(f"Aktif: id={args.id}")
        elif args.perintah == "rollback":
            cetak(f"Rollback ke id={registri_model.rollback(conn)}")
        else:
            for m in registri_model.daftar(conn):
                cetak(f"{m['id']}\t{m['versi']}\t{m['status']}\t{m['path']}")
        if args.perintah != "status":
            cetak("Restart aplikasi agar model aktif yang baru dimuat.")
        return 0
    except (registri_model.ModelTidakDitemukan, registri_model.TidakAdaModelUntukRollback) as exc:
        cetak(str(exc))
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(jalankan(sys.argv[1:]))
