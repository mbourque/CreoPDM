from pathlib import Path

import pytest

from creopdm.exceptions import PathValidationError
from creopdm.utils.paths import (
    assert_safe_relative_path,
    ensure_within,
    is_within,
    require_within_product,
    validate_product_location,
)


def test_relative_path_accepts_nested_file():
    path = assert_safe_relative_path("CAD/shaft.prt")
    assert path.as_posix() == "CAD/shaft.prt"


def test_relative_path_rejects_traversal():
    with pytest.raises(PathValidationError):
        assert_safe_relative_path("../secret.prt")
    with pytest.raises(PathValidationError):
        assert_safe_relative_path("CAD/../../outside.prt")
    with pytest.raises(PathValidationError):
        assert_safe_relative_path("/etc/passwd")
    with pytest.raises(PathValidationError):
        assert_safe_relative_path("C:/Windows/system32")


def test_ensure_within_rejects_escape(tmp_path: Path):
    base = tmp_path / "repo"
    base.mkdir()
    with pytest.raises(PathValidationError):
        ensure_within(base, tmp_path / "other" / "file.txt")


def test_require_within_product_allows_nested_and_rejects_outside(tmp_path: Path):
    repo = tmp_path / "proj"
    nested = repo / "lib"
    nested.mkdir(parents=True)
    inside = nested / "pin.prt"
    inside.write_bytes(b"ok")
    assert is_within(repo, inside)
    assert require_within_product(repo, nested) == nested.resolve()
    outsider = tmp_path / "other" / "pin.prt"
    outsider.parent.mkdir()
    outsider.write_bytes(b"nope")
    assert not is_within(repo, outsider)
    with pytest.raises(PathValidationError, match="product location"):
        require_within_product(repo, outsider)


def test_validate_product_location_requires_parent(tmp_path: Path):
    with pytest.raises(PathValidationError):
        validate_product_location(tmp_path / "missing-parent" / "proj")
    location = validate_product_location(tmp_path / "proj")
    assert location.name == "proj"
