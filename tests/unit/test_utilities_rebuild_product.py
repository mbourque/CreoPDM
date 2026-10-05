"""Utilities → Rebuild product database / clear metadata / clear Where Used."""

from __future__ import annotations

import subprocess
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from creopdm.app import build_context
from creopdm.config import ConfigManager
from creopdm.constants import DependencyType
from creopdm.exceptions import ValidationAppError
from creopdm.models.dependency import Dependency
from creopdm.models.object import EngineeringObject
from creopdm.models.parameter import Parameter
from creopdm.models.product import Product
from creopdm.models.version import ObjectVersion
from creopdm.services.utilities_service import (
    rebuild_product_database_from_vault,
    repair_product_database,
)
from creopdm.utils.identity import StaticUserProvider
from tests.conftest import requires_git


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _init_vault(path: Path, files: dict[str, str]) -> str:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init")
    for rel, text in files.items():
        target = path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        _git(path, "add", rel)
    _git(
        path,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@creopdm.local",
        "commit",
        "-m",
        "init",
    )
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(path),
        check=True,
        capture_output=True,
        encoding="utf-8",
    ).stdout.strip()
    return head


@requires_git
def test_rebuild_registers_tip_files_and_drops_stale(data_dir, identity: StaticUserProvider):
    ctx = build_context(ConfigManager(), users=identity)
    vaults = ctx.config.vaults_dir
    folder = "rebuild-prod-2"
    vault = vaults / folder
    head = _init_vault(
        vault,
        {
            "shaft.prt": "part-bytes\n",
            "assy.asm": "asm-bytes\n",
        },
    )

    with ctx.session_factory() as db:
        product = Product(
            uuid=str(uuid.uuid4()),
            name="Rebuild Two",
            vault_folder=folder,
            repository_path=str(vault),
            default_branch="main",
        )
        db.add(product)
        db.flush()
        stale = EngineeringObject(
            uuid=str(uuid.uuid4()),
            product_id=product.id,
            name="gone",
            filename="gone.prt",
            extension="prt",
            object_type="CREO_PART",
            relative_path="gone.prt",
        )
        db.add(stale)
        db.flush()
        stale_ver = ObjectVersion(
            uuid=str(uuid.uuid4()),
            object_id=stale.id,
            revision="A",
            iteration=1,
            filename="gone.prt",
            relative_path="gone.prt",
            git_commit_hash="deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
            content_hash="b" * 64,
            file_size=1,
            created_by="old",
            comment="stale",
        )
        db.add(stale_ver)
        db.flush()
        stale.current_version_id = stale_ver.id
        db.commit()

        result = rebuild_product_database_from_vault(
            ctx,
            db,
            product_uuid=product.uuid,
            confirm_name="Rebuild Two",
        )
        db.commit()

        assert result.objects_removed == 1
        assert result.files_registered == 2
        assert result.head == head

        objects = list(
            db.scalars(
                select(EngineeringObject).where(EngineeringObject.product_id == product.id)
            ).all()
        )
        names = sorted(obj.filename for obj in objects)
        assert names == ["assy.asm", "shaft.prt"]
        assert all(obj.current_version_id for obj in objects)
        for obj in objects:
            ver = db.get(ObjectVersion, obj.current_version_id)
            assert ver is not None
            assert ver.git_commit_hash == head
            assert ver.content_hash
            assert obj.filename != "gone.prt"


@requires_git
def test_rebuild_requires_exact_name(data_dir, identity: StaticUserProvider):
    ctx = build_context(ConfigManager(), users=identity)
    folder = "rebuild-name"
    vault = ctx.config.vaults_dir / folder
    _init_vault(vault, {"a.txt": "a\n"})
    with ctx.session_factory() as db:
        product = Product(
            uuid=str(uuid.uuid4()),
            name="Exact Name",
            vault_folder=folder,
            repository_path=str(vault),
            default_branch="main",
        )
        db.add(product)
        db.commit()
        with pytest.raises(ValidationAppError, match="exactly"):
            rebuild_product_database_from_vault(
                ctx,
                db,
                product_uuid=product.uuid,
                confirm_name="wrong",
            )


def test_repair_requires_at_least_one_action(data_dir, identity: StaticUserProvider):
    ctx = build_context(ConfigManager(), users=identity)
    with ctx.session_factory() as db:
        product = Product(
            uuid=str(uuid.uuid4()),
            name="No Action",
            vault_folder="no-action",
            repository_path=str(ctx.config.vaults_dir / "no-action"),
            default_branch="main",
        )
        db.add(product)
        db.commit()
        with pytest.raises(ValidationAppError, match="at least one action"):
            repair_product_database(
                ctx,
                db,
                product_uuid=product.uuid,
                confirm_name="No Action",
            )


def test_clear_metadata_keeps_file_rows(data_dir, identity: StaticUserProvider):
    """Delete Creo metadata must not drop EngineeringObject / tip versions."""
    ctx = build_context(ConfigManager(), users=identity)
    with ctx.session_factory() as db:
        product = Product(
            uuid=str(uuid.uuid4()),
            name="Meta Clear",
            vault_folder="meta-clear",
            repository_path=str(ctx.config.vaults_dir / "meta-clear"),
            default_branch="main",
        )
        db.add(product)
        db.flush()
        obj = EngineeringObject(
            uuid=str(uuid.uuid4()),
            product_id=product.id,
            name="shaft",
            filename="shaft.prt",
            extension="prt",
            object_type="CREO_PART",
            relative_path="shaft.prt",
        )
        db.add(obj)
        db.flush()
        ver = ObjectVersion(
            uuid=str(uuid.uuid4()),
            object_id=obj.id,
            revision="A",
            iteration=1,
            filename="shaft.prt",
            relative_path="shaft.prt",
            identity_json='{"name":"shaft"}',
            bom_json='{"items":[]}',
            materials_json='{"mat":"steel"}',
            units_json='{"len":"mm"}',
            mass_json='{"mass":1}',
            family_table_json='{"rows":[]}',
            features_json='{"n":1}',
            git_commit_hash="a" * 40,
            content_hash="c" * 64,
            file_size=10,
            created_by="tester",
            comment="tip",
        )
        db.add(ver)
        db.flush()
        obj.current_version_id = ver.id
        db.add(
            Parameter(
                object_id=obj.id,
                version_id=ver.id,
                name="PTC_MATERIAL",
                value="STEEL",
            )
        )
        db.commit()

        result = repair_product_database(
            ctx,
            db,
            product_uuid=product.uuid,
            confirm_name="Meta Clear",
            clear_metadata=True,
        )
        db.commit()

        assert result.metadata_cleared is True
        assert result.rebuilt is False
        assert result.metadata_versions == 1
        still = db.get(EngineeringObject, obj.id)
        assert still is not None
        tip = db.get(ObjectVersion, ver.id)
        assert tip is not None
        assert tip.identity_json is None
        assert tip.bom_json is None
        assert tip.materials_json is None
        assert tip.units_json is None
        assert tip.mass_json is None
        assert tip.family_table_json is None
        assert tip.features_json is None
        params = list(
            db.scalars(select(Parameter).where(Parameter.object_id == obj.id)).all()
        )
        assert params == []


def test_rebuild_where_used_replaces_stale_edges(
    data_dir, identity: StaticUserProvider
):
    """Delete-and-rebuild Where Used clears stale links and re-indexes from vault."""
    ctx = build_context(ConfigManager(), users=identity)
    vault = ctx.config.workspace_for_product("wu-rebuild")
    vault.mkdir(parents=True, exist_ok=True)
    (vault / "assy.asm").write_bytes(b"\x00".join([b"shaft.prt"]))
    (vault / "shaft.prt").write_bytes(b"part")
    (vault / "orphan.prt").write_bytes(b"orphan")

    with ctx.session_factory() as db:
        product = Product(
            uuid=str(uuid.uuid4()),
            name="WU Rebuild",
            vault_folder="wu-rebuild",
            repository_path=str(vault),
            default_branch="main",
        )
        db.add(product)
        db.flush()
        parent = EngineeringObject(
            uuid=str(uuid.uuid4()),
            product_id=product.id,
            name="assy",
            filename="assy.asm",
            extension="asm",
            object_type="CREO_ASSEMBLY",
            relative_path="assy.asm",
        )
        child = EngineeringObject(
            uuid=str(uuid.uuid4()),
            product_id=product.id,
            name="shaft",
            filename="shaft.prt",
            extension="prt",
            object_type="CREO_PART",
            relative_path="shaft.prt",
        )
        orphan = EngineeringObject(
            uuid=str(uuid.uuid4()),
            product_id=product.id,
            name="orphan",
            filename="orphan.prt",
            extension="prt",
            object_type="CREO_PART",
            relative_path="orphan.prt",
        )
        db.add_all([parent, child, orphan])
        db.flush()
        ver = ObjectVersion(
            uuid=str(uuid.uuid4()),
            object_id=child.id,
            revision="A",
            iteration=1,
            filename="shaft.prt",
            relative_path="shaft.prt",
            identity_json='{"keep":true}',
            git_commit_hash="b" * 40,
            content_hash="d" * 64,
            file_size=10,
            created_by="tester",
            comment="tip",
        )
        db.add(ver)
        db.flush()
        child.current_version_id = ver.id
        # Stale false parent→orphan edge that vault bytes do not support.
        db.add(
            Dependency(
                product_id=product.id,
                parent_object_id=parent.id,
                child_object_id=orphan.id,
                dependency_type=DependencyType.ASSEMBLY_MEMBER.value,
            )
        )
        db.commit()

        result = repair_product_database(
            ctx,
            db,
            product_uuid=product.uuid,
            confirm_name="WU Rebuild",
            rebuild_where_used=True,
        )
        db.commit()

        assert result.where_used_rebuilt is True
        assert result.rebuilt is False
        assert result.metadata_cleared is False
        edges = list(
            db.scalars(
                select(Dependency).where(Dependency.product_id == product.id)
            ).all()
        )
        assert any(
            edge.parent_object_id == parent.id and edge.child_object_id == child.id
            for edge in edges
        )
        assert not any(
            edge.parent_object_id == parent.id and edge.child_object_id == orphan.id
            for edge in edges
        )
        tip = db.get(ObjectVersion, ver.id)
        assert tip is not None
        assert tip.identity_json == '{"keep":true}'


def test_repair_clear_metadata_and_rebuild_where_used_together(
    data_dir, identity: StaticUserProvider
):
    ctx = build_context(ConfigManager(), users=identity)
    vault = ctx.config.workspace_for_product("both-repair")
    vault.mkdir(parents=True, exist_ok=True)
    (vault / "assy.asm").write_bytes(b"\x00".join([b"part.prt"]))
    (vault / "part.prt").write_bytes(b"part")

    with ctx.session_factory() as db:
        product = Product(
            uuid=str(uuid.uuid4()),
            name="Both Repair",
            vault_folder="both-repair",
            repository_path=str(vault),
            default_branch="main",
        )
        db.add(product)
        db.flush()
        parent = EngineeringObject(
            uuid=str(uuid.uuid4()),
            product_id=product.id,
            name="assy",
            filename="assy.asm",
            extension="asm",
            object_type="CREO_ASSEMBLY",
            relative_path="assy.asm",
        )
        child = EngineeringObject(
            uuid=str(uuid.uuid4()),
            product_id=product.id,
            name="part",
            filename="part.prt",
            extension="prt",
            object_type="CREO_PART",
            relative_path="part.prt",
        )
        db.add_all([parent, child])
        db.flush()
        ver = ObjectVersion(
            uuid=str(uuid.uuid4()),
            object_id=child.id,
            revision="A",
            iteration=1,
            filename="part.prt",
            relative_path="part.prt",
            bom_json="[]",
            git_commit_hash="e" * 40,
            content_hash="f" * 64,
            file_size=4,
            created_by="tester",
            comment="tip",
        )
        db.add(ver)
        db.flush()
        child.current_version_id = ver.id
        db.add(
            Dependency(
                product_id=product.id,
                parent_object_id=parent.id,
                child_object_id=child.id,
                dependency_type=DependencyType.ASSEMBLY_MEMBER.value,
            )
        )
        db.commit()

        result = repair_product_database(
            ctx,
            db,
            product_uuid=product.uuid,
            confirm_name="Both Repair",
            clear_metadata=True,
            rebuild_where_used=True,
        )
        db.commit()

        assert result.metadata_cleared is True
        assert result.where_used_rebuilt is True
        assert result.rebuilt is False
        assert db.get(ObjectVersion, ver.id).bom_json is None
        edges = list(
            db.scalars(
                select(Dependency).where(Dependency.product_id == product.id)
            ).all()
        )
        assert any(
            edge.parent_object_id == parent.id and edge.child_object_id == child.id
            for edge in edges
        )
