"""Password hashing (Argon2id). Never store plaintext passwords."""

from __future__ import annotations

from pwdlib import PasswordHash

_hasher = PasswordHash.recommended()


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, password_hash: str) -> bool:
    if not plain or not password_hash:
        return False
    try:
        return _hasher.verify(plain, password_hash)
    except Exception:
        return False
