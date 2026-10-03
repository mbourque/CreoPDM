"""Admin compact product vault history — tip-only Git + History prune."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from creopdm.exceptions import ValidationAppError
from creopdm.models.object import EngineeringObject
from creopdm.models.version import ObjectVersion
from creopdm.services.git_service import GitService
from creopdm.services.utilities_service import compact_product_vault_history
from creopdm.utils.identity import UserIdentity
from tests.conftest import requires_git


def _create_product(client, name: str = "Compact Me"):
    response = client.post("/api/products", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


@requires_git
def test_compact_to_tip_drops_removed_file_blobs(tmp_path):
    """Orphan tip commit + gc must make Unregister leftovers unreachable."""
    vault = tmp_path / "vault"
    vault.mkdir()
    git = GitService()
    author = UserIdentity("Admin", "TEST-PC")
    git.init_repository(vault, "main")
    keep = vault / "keep.prt"
    keep.write_bytes(b"keep-tip")
    gone = vault / "gone.prt"
    unique = b"UNIQUE-REMOVED-BLOB-" + (b"x" * 4096)
    gone.write_bytes(unique)
    git.stage_files(vault, ["keep.prt", "gone.prt"])
    git.commit(vault, "Add both", author)
    blob = git._run(["hash-object", "-t", "blob", "--", "gone.prt"], cwd=vault).stdout.strip()
    assert blob
    assert git._run(["cat-file", "-e", blob], cwd=vault, check=False).returncode == 0

    git.remove_files(vault, ["gone.prt"], keep_working_copy=False)
    git.commit(vault, "Unregister gone.prt", author)
    # Still reachable via old commit before compact.
    assert git._run(["cat-file", "-e", blob], cwd=vault, check=False).returncode == 0

    head = git.compact_to_tip(vault, author=author, message="Compact", branch="main")
    assert len(head) >= 40
    assert (vault / "keep.prt").read_bytes() == b"keep-tip"
    assert not (vault / "gone.prt").exists()
    history = git.get_history(vault)
    assert len(history) == 1
    assert history[0].commit_hash == head
    assert git._run(["cat-file", "-e", blob], cwd=vault, check=False).returncode != 0


@requires_git
def test_compact_aligns_dirty_vault_after_purge_drift(tmp_path):
    """Remove/purge can leave deleted tracked paths; compact must align then squash."""
    vault = tmp_path / "vault"
    vault.mkdir()
    git = GitService()
    author = UserIdentity("Admin", "TEST-PC")
    git.init_repository(vault, "main")
    (vault / "keep.prt").write_bytes(b"keep")
    (vault / "extra.prt.2").write_bytes(b"purge-me")
    git.stage_files(vault, ["keep.prt", "extra.prt.2"])
    git.commit(vault, "Add", author)
    # Simulate purge deleting a tracked sibling without a git rm commit.
    (vault / "extra.prt.2").unlink()
    assert git.is_dirty(vault)

    head = git.compact_to_tip(vault, author=author, message="Compact", branch="main")
    assert not git.is_dirty(vault)
    assert (vault / "keep.prt").read_bytes() == b"keep"
    assert not (vault / "extra.prt.2").exists()
    assert len(git.get_history(vault)) == 1
    assert git.get_head(vault) == head


@requires_git
def test_compact_product_vault_prunes_history_and_rejects_gates(client, app, data_dir):
    ctx = app.state.ctx
    product = _create_product(client, "Robot Compact")
    folder = product.get("vault_folder") or product["uuid"]
    created = client.post(
        f"/api/products/{product['uuid']}/objects",
        files={"file": ("shaft.prt", b"v1-content", "application/octet-stream")},
        data={"comment": "Initial"},
    )
    assert created.status_code == 201, created.text
    obj = created.json()
    assert client.post(f"/api/objects/{obj['uuid']}/checkout").status_code == 200
    workspace = data_dir / "vaults" / folder / "shaft.prt"
    workspace.write_bytes(b"v2-content")
    checked_in = client.post(
        f"/api/objects/{obj['uuid']}/checkin",
        json={"comment": "Second version"},
    )
    assert checked_in.status_code == 200, checked_in.text
    history = client.get(f"/api/objects/{obj['uuid']}/history").json()
    assert len(history) >= 2

    # Wrong name
    with ctx.session_factory() as db:
        with pytest.raises(ValidationAppError, match="exactly"):
            compact_product_vault_history(
                ctx,
                db,
                product_uuid=product["uuid"],
                confirm_name="Wrong Name",
            )

    # Active checkout blocks
    assert client.post(f"/api/objects/{obj['uuid']}/checkout").status_code == 200
    with ctx.session_factory() as db:
        with pytest.raises(ValidationAppError, match="checkout"):
            compact_product_vault_history(
                ctx,
                db,
                product_uuid=product["uuid"],
                confirm_name="Robot Compact",
            )
    assert client.post(f"/api/objects/{obj['uuid']}/undo-checkout").status_code == 200

    # Dirty vault is aligned (not blocked) — leftover untracked after purge/remove.
    vault = data_dir / "vaults" / folder
    dirty = vault / "untracked-dirt.bin"
    dirty.write_bytes(b"dirt")

    with ctx.session_factory() as db:
        result = compact_product_vault_history(
            ctx,
            db,
            product_uuid=product["uuid"],
            confirm_name="Robot Compact",
        )
        db.commit()
        assert result.product_name == "Robot Compact"
        assert result.versions_removed >= 1
        assert result.new_head

        versions = list(
            db.scalars(
                select(ObjectVersion)
                .join(EngineeringObject, EngineeringObject.id == ObjectVersion.object_id)
                .where(EngineeringObject.uuid == obj["uuid"])
            ).all()
        )
        assert len(versions) == 1
        assert versions[0].git_commit_hash == result.new_head
        assert versions[0].iteration == checked_in.json()["iteration"]

    tip_history = client.get(f"/api/objects/{obj['uuid']}/history").json()
    assert len(tip_history) == 1
    assert tip_history[0]["comment"] == "Second version"
    assert (vault / "shaft.prt").read_bytes() == b"v2-content"
    git = GitService()
    assert not git.is_dirty(vault)
    git_history = git.get_history(vault)
    assert len(git_history) == 1


@requires_git
def test_compact_drops_blobs_after_remove_from_product(client, app, data_dir):
    ctx = app.state.ctx
    product = _create_product(client, "Remove Then Compact")
    folder = product.get("vault_folder") or product["uuid"]
    unique = b"REMOVE-THEN-COMPACT-" + (b"z" * 8192)
    created = client.post(
        f"/api/products/{product['uuid']}/objects",
        files={"file": ("gone.prt", unique, "application/octet-stream")},
        data={"comment": "Temp"},
    )
    assert created.status_code == 201, created.text
    obj = created.json()
    vault = data_dir / "vaults" / folder
    git = GitService()
    blob = git._run(["hash-object", "-t", "blob", "--", "gone.prt"], cwd=vault).stdout.strip()
    assert blob

    removed = client.delete(f"/api/objects/{obj['uuid']}")
    assert removed.status_code == 204, removed.text
    assert git._run(["cat-file", "-e", blob], cwd=vault, check=False).returncode == 0

    with ctx.session_factory() as db:
        result = compact_product_vault_history(
            ctx,
            db,
            product_uuid=product["uuid"],
            confirm_name="Remove Then Compact",
        )
        db.commit()
        assert result.new_head

    assert git._run(["cat-file", "-e", blob], cwd=vault, check=False).returncode != 0
