from pathlib import Path

import pytest

from creopdm.exceptions import PathValidationError
from creopdm.utils.paths import assert_safe_relative_path, ensure_within, validate_project_location


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


def test_validate_project_location_requires_parent(tmp_path: Path):
    with pytest.raises(PathValidationError):
        validate_project_location(tmp_path / "missing-parent" / "proj")
    location = validate_project_location(tmp_path / "proj")
    assert location.name == "proj"
