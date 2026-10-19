"""Hash password dengan `scrypt` (stdlib). Format: `scrypt$n$r$p$salt_b64$hash_b64`."""

import base64
import functools
import hashlib
import hmac
import secrets
import unicodedata

N = 2**15
R = 8
P = 1
DKLEN = 32
MAXMEM = 256 * 1024 * 1024
PANJANG_MAKS = 1024
PANJANG_MIN = 10
N_MAKS, R_MAKS, P_MAKS = 2**20, 32, 16


class PasswordLemah(ValueError):
    """Password tidak memenuhi syarat minimal."""


def _bytes(password: str) -> bytes:
    """Normalisasi NFKC lalu UTF-8; terlalu panjang -> ValueError."""
    if len(password) > PANJANG_MAKS:
        raise ValueError(f"password maksimal {PANJANG_MAKS} karakter")
    return unicodedata.normalize("NFKC", password).encode("utf-8")


def _b64(data: bytes) -> str:
    """Base64 tanpa padding."""
    return base64.b64encode(data).decode("ascii").rstrip("=")


def _unb64(teks: str) -> bytes:
    """Kebalikan `_b64`."""
    return base64.b64decode(teks + "=" * (-len(teks) % 4), validate=True)


def hash_password(password: str) -> str:
    """Hash `password` dengan salt acak dan parameter saat ini."""
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(_bytes(password), salt=salt, n=N, r=R, p=P, dklen=DKLEN, maxmem=MAXMEM)
    return f"scrypt${N}${R}${P}${_b64(salt)}${_b64(h)}"


def _urai(tersimpan: str) -> tuple[int, int, int, bytes, bytes] | None:
    """Urai string hash; format rusak atau parameter di luar batas -> None."""
    try:
        tag, n, r, p, salt, h = tersimpan.split("$")
        n_i, r_i, p_i = int(n), int(r), int(p)
        if tag != "scrypt" or n_i < 2 or n_i & (n_i - 1) or n_i > N_MAKS:
            return None
        if not 1 <= r_i <= R_MAKS or not 1 <= p_i <= P_MAKS:
            return None
        return n_i, r_i, p_i, _unb64(salt), _unb64(h)
    except (ValueError, TypeError):
        return None


def verifikasi_password(password: str, tersimpan: str) -> bool:
    """True bila `password` cocok dengan hash `tersimpan`; format rusak -> False."""
    urai = _urai(tersimpan)
    if urai is None:
        return False
    n, r, p, salt, h = urai
    try:
        kandidat = hashlib.scrypt(
            _bytes(password), salt=salt, n=n, r=r, p=p, dklen=len(h), maxmem=MAXMEM
        )
    except ValueError:
        return False
    return hmac.compare_digest(kandidat, h)


def perlu_rehash(tersimpan: str) -> bool:
    """True bila parameter hash lebih lemah dari konstanta saat ini."""
    urai = _urai(tersimpan)
    if urai is None:
        return True
    n, r, p, _, h = urai
    return (n, r, p) < (N, R, P) or len(h) < DKLEN


def validasi_kekuatan(password: str, username: str = "") -> None:
    """Minimal 10 karakter dan tidak sama dengan username; selain itu PasswordLemah."""
    if len(password) < PANJANG_MIN:
        raise PasswordLemah(f"Password minimal {PANJANG_MIN} karakter.")
    if len(password) > PANJANG_MAKS:
        raise PasswordLemah(f"Password maksimal {PANJANG_MAKS} karakter.")
    if username and password.lower() == username.lower():
        raise PasswordLemah("Password tidak boleh sama dengan username.")


@functools.cache
def hash_dummy() -> str:
    """Hash tetap untuk menyamakan waktu saat username tidak ada."""
    return hash_password(secrets.token_urlsafe(16))
