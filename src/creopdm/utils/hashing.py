"""SHA-256 content hashing independent of Git object hashes."""

from __future__ import annotations

import hashlib
from pathlib import Path

from creopdm.exceptions import PathValidationError

CHUNK_SIZE = 1024 * 1024


def calculate_sha256(path: Path, chunk_size: int = CHUNK_SIZE) -> str:
    """Return the SHA-256 hex digest of a file's contents."""
    if not path.is_file():
        raise PathValidationError(f"Cannot hash missing file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()
