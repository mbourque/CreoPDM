import hashlib
from pathlib import Path

from creopdm.utils.hashing import calculate_sha256


def test_calculate_sha256(tmp_path: Path):
    payload = b"CreoPDM hash fixture\n"
    path = tmp_path / "sample.bin"
    path.write_bytes(payload)
    digest = calculate_sha256(path)
    assert digest == hashlib.sha256(payload).hexdigest()
    other = tmp_path / "other.bin"
    other.write_bytes(b"different")
    assert calculate_sha256(other) != digest
