"""Utilities → Rebuild product database from vault Git tip."""

from __future__ import annotations

import subprocess
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from creopdm.app import build_context
from creopdm.config import ConfigManager
from creopdm.exceptions import ValidationAppError
from creopdm.models.object import EngineeringObject
from creopdm.models.product import Product
from creopdm.models.version import ObjectVersion
from creopdm.services.utilities_service import rebuild_product_database_from_vault
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
