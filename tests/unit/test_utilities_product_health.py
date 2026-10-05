"""Utilities → Health lightweight product vault / tip checks."""

from __future__ import annotations

import subprocess
import uuid
from pathlib import Path

from creopdm.app import build_context
from creopdm.config import ConfigManager
from creopdm.models.object import EngineeringObject
from creopdm.models.product import Product
from creopdm.models.version import ObjectVersion
from creopdm.services.utilities_service import collect_product_health
from creopdm.utils.identity import StaticUserProvider
from tests.conftest import requires_git


def _add_product(db, *, name: str, folder: str, data_dir: Path) -> Product:
    product = Product(
        uuid=str(uuid.uuid4()),
        name=name,
        vault_folder=folder,
        repository_path=str(data_dir / "vaults" / folder),
        default_branch="main",
    )
    db.add(product)
    db.flush()
    return product


@requires_git
def test_collect_product_health_ok_and_missing_vault(data_dir, identity: StaticUserProvider):
    ctx = build_context(ConfigManager(), users=identity)
    vaults = ctx.config.vaults_dir
    vaults.mkdir(parents=True, exist_ok=True)

    good_folder = "good-prod"
    good_path = vaults / good_folder
    good_path.mkdir()
    subprocess.run(
        ["git", "init"],
        cwd=str(good_path),
        check=True,
        capture_output=True,
    )
    (good_path / "readme.txt").write_text("ok\n", encoding="utf-8")
    subprocess.run(["git", "add", "readme.txt"], cwd=str(good_path), check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@creopdm.local",
            "commit",
            "-m",
            "init",
        ],
        cwd=str(good_path),
        check=True,
        capture_output=True,
    )

    with ctx.session_factory() as db:
        _add_product(db, name="Good", folder=good_folder, data_dir=data_dir)
        _add_product(db, name="Missing", folder="missing-prod", data_dir=data_dir)
        db.commit()

        health = collect_product_health(ctx, db)

    assert health.checked == 2
    assert health.issue_count >= 1
    assert health.status == "degraded"
    codes = {issue.code for issue in health.issues}
    assert "missing_vault" in codes
    assert not any(issue.code == "missing_vault" and issue.product_name == "Good" for issue in health.issues)


@requires_git
def test_collect_product_health_orphan_vault_and_missing_git(
    data_dir, identity: StaticUserProvider
):
    ctx = build_context(ConfigManager(), users=identity)
    vaults = ctx.config.vaults_dir
    vaults.mkdir(parents=True, exist_ok=True)
    (vaults / "orphan-folder").mkdir()
    empty_git = vaults / "no-git-prod"
    empty_git.mkdir()

    with ctx.session_factory() as db:
        _add_product(db, name="NoGit", folder="no-git-prod", data_dir=data_dir)
        db.commit()
        health = collect_product_health(ctx, db)

    codes = {issue.code for issue in health.issues}
    assert "orphan_vault" in codes
    assert "missing_git" in codes
    assert health.status == "degraded"


@requires_git
def test_collect_product_health_missing_tip_commit(data_dir, identity: StaticUserProvider):
    ctx = build_context(ConfigManager(), users=identity)
    vaults = ctx.config.vaults_dir
    vaults.mkdir(parents=True, exist_ok=True)
    folder = "tip-prod"
    path = vaults / folder
    path.mkdir()
    subprocess.run(["git", "init"], cwd=str(path), check=True, capture_output=True)
    (path / "a.txt").write_text("a\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.txt"], cwd=str(path), check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@creopdm.local",
            "commit",
            "-m",
            "init",
        ],
        cwd=str(path),
        check=True,
        capture_output=True,
    )

    with ctx.session_factory() as db:
        product = _add_product(db, name="Tip", folder=folder, data_dir=data_dir)
        obj = EngineeringObject(
            uuid=str(uuid.uuid4()),
            product_id=product.id,
            name="part",
            filename="part.prt",
            extension="prt",
            object_type="CREO_PART",
            relative_path="part.prt",
        )
        db.add(obj)
        db.flush()
        version = ObjectVersion(
            uuid=str(uuid.uuid4()),
            object_id=obj.id,
            revision="A",
            iteration=1,
            filename="part.prt",
            relative_path="part.prt",
            git_commit_hash="deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
            content_hash="a" * 64,
            file_size=1,
            created_by="test",
            comment="tip",
        )
        db.add(version)
        db.flush()
        obj.current_version_id = version.id
        db.commit()

        health = collect_product_health(ctx, db)

    assert any(issue.code == "missing_tip" for issue in health.issues)
    assert health.status == "degraded"


def test_collect_product_health_empty_ok(data_dir, identity: StaticUserProvider):
    ctx = build_context(ConfigManager(), users=identity)
    with ctx.session_factory() as db:
        health = collect_product_health(ctx, db)
    assert health.checked == 0
    assert health.issue_count == 0
    assert health.status == "ok"
    assert "No products" in health.summary
