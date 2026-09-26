"""User-interaction validations from docs/user-interactions.md (gaps / negatives)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from creopdm.schemas.common import BatchRemoveRequest, CreateFolderRequest


def test_batch_remove_request_requires_files_or_folder():
    """N22 / schema: empty remove payload must fail before the API runs."""
    with pytest.raises(ValidationError) as exc:
        BatchRemoveRequest()
    assert "Choose files or a folder to remove." in str(exc.value)


def test_batch_remove_request_folders_require_project_when_no_ids():
    with pytest.raises(ValidationError) as exc:
        BatchRemoveRequest(folder_paths=["Drawings"])
    assert "Choose a project before removing folders." in str(exc.value)


def test_batch_remove_request_accepts_folders_with_project():
    body = BatchRemoveRequest(folder_paths=["Drawings/RevA", "  Kit\\ "], project_id=" abc ")
    assert body.folder_paths == ["Drawings/RevA", "Kit"]
    assert body.project_id == "abc"
    assert body.object_ids == []


def test_batch_remove_request_accepts_ids_without_project():
    body = BatchRemoveRequest(object_ids=["  u1  ", "", "u2"])
    assert body.object_ids == ["u1", "u2"]
    assert body.folder_paths == []


def test_create_folder_request_rejects_empty_name():
    with pytest.raises(ValidationError):
        CreateFolderRequest(name="")
    with pytest.raises(ValidationError):
        CreateFolderRequest(name="x" * 201)
