"""Unit tests for Export ▾ vault tip zip packing."""

from __future__ import annotations

import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from creopdm.exceptions import ValidationAppError
from creopdm.services.export_zip import build_export_zip, export_zip_basename
from creopdm.services.workspace_service import WorkspaceService
from creopdm.config import ConfigManager


def test_export_zip_basename_sanitizes():
    product = SimpleNamespace(name="Robot Arm!", vault_folder="robot", uuid="abc")
    assert export_zip_basename(product, selected=False) == "Robot_Arm-export.zip"
    assert export_zip_basename(product, selected=True).endswith("-selection.zip")


def test_build_export_zip_packs_nested_tip(tmp_path: Path):
    manager = ConfigManager(tmp_path / "data")
    manager.ensure_layout()
    workspaces = WorkspaceService(manager, None)
    product = SimpleNamespace(uuid="p1", vault_folder="p1", name="Demo")
    vault = workspaces.vault_for(product)
    nested = vault / "lib" / "pin.prt"
    nested.parent.mkdir(parents=True)
    nested.write_bytes(b"pin-bytes")
    (vault / "top.asm").write_bytes(b"top-bytes")
    objects = [
        SimpleNamespace(
            uuid="o1",
            filename="pin.prt",
            relative_path="lib/pin.prt",
            current_version=None,
        ),
        SimpleNamespace(
            uuid="o2",
            filename="top.asm",
            relative_path="top.asm",
            current_version=None,
        ),
    ]
    archive, count = build_export_zip(workspaces, product, objects)
    try:
        assert count == 2
        with zipfile.ZipFile(archive) as zf:
            names = set(zf.namelist())
            assert names == {"lib/pin.prt", "top.asm"}
            assert zf.read("lib/pin.prt") == b"pin-bytes"
    finally:
        archive.unlink(missing_ok=True)


def test_build_export_zip_strips_creo_save_number(tmp_path: Path):
    """Export must hand out logical names even if a legacy vault tip is still numbered."""
    manager = ConfigManager(tmp_path / "data")
    manager.ensure_layout()
    workspaces = WorkspaceService(manager, None)
    product = SimpleNamespace(uuid="p1", vault_folder="p1", name="Demo")
    vault = workspaces.vault_for(product)
    numbered = vault / "lib" / "shaft.prt.3"
    numbered.parent.mkdir(parents=True)
    numbered.write_bytes(b"shaft-bytes")
    objects = [
        SimpleNamespace(
            uuid="o1",
            filename="shaft.prt.3",
            relative_path="lib/shaft.prt.3",
            current_version=None,
        ),
    ]
    archive, count = build_export_zip(workspaces, product, objects)
    try:
        assert count == 1
        with zipfile.ZipFile(archive) as zf:
            assert zf.namelist() == ["lib/shaft.prt"]
            assert zf.read("lib/shaft.prt") == b"shaft-bytes"
    finally:
        archive.unlink(missing_ok=True)


def test_build_export_zip_rejects_empty(tmp_path: Path):
    manager = ConfigManager(tmp_path / "data")
    manager.ensure_layout()
    workspaces = WorkspaceService(manager, None)
    product = SimpleNamespace(uuid="p1", vault_folder="p1", name="Demo")
    with pytest.raises(ValidationAppError, match="Nothing to export"):
        build_export_zip(workspaces, product, [])


def test_export_permissions_in_authoring_defaults():
    from creopdm.auth_constants import (
        PERMISSION_OBJECTS_EXPORT,
        PERMISSION_PRODUCTS_EXPORT,
        STARTER_ROLE_PERMISSION_KEYS,
        StarterRole,
    )

    engineer = STARTER_ROLE_PERMISSION_KEYS[StarterRole.ENGINEER.value]
    pdm = STARTER_ROLE_PERMISSION_KEYS[StarterRole.PDM_MANAGER.value]
    viewer = STARTER_ROLE_PERMISSION_KEYS[StarterRole.VIEWER.value]
    assert PERMISSION_PRODUCTS_EXPORT in engineer
    assert PERMISSION_OBJECTS_EXPORT in engineer
    assert PERMISSION_PRODUCTS_EXPORT in pdm
    assert PERMISSION_OBJECTS_EXPORT in pdm
    assert PERMISSION_PRODUCTS_EXPORT not in viewer
    assert PERMISSION_OBJECTS_EXPORT not in viewer
