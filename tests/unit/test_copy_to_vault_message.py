"""Copy to Vault: say what happened when there was nothing to copy."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from creopdm.app import build_context, create_app
from creopdm.config import ConfigManager
from tests.conftest import requires_git
from tests.unit.test_baselines import _product, _signed_in_admin

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def auth_ctx(data_dir):
    return build_context(ConfigManager())


@pytest.fixture()
def auth_client(auth_ctx):
    with TestClient(create_app(auth_ctx)) as client:
        yield client


@requires_git
def test_files_already_in_the_vault_are_reported_as_skipped_not_silently_dropped(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    _product_row, objects = _product(auth_client, "Gearbox", ("shaft.prt", "gear.prt"))
    ids = [objects["shaft.prt"]["uuid"], objects["gear.prt"]["uuid"]]
    done = auth_client.post("/api/objects/batch/workspace", json={"object_ids": ids})
    assert done.status_code == 200, done.text
    body = done.json()
    assert body["ok"] == [] and body["failed"] == []
    assert sorted(item["filename"] for item in body["skipped"]) == ["gear.prt", "shaft.prt"]


@requires_git
def test_a_file_missing_from_the_vault_is_copied_back(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, objects = _product(auth_client, "Gearbox", ("shaft.prt",))
    vault = Path(auth_ctx.config.workspace_root()) / product["vault_folder"]
    import os

    os.chmod(vault / "shaft.prt", 0o666)  # vault copies are read-only
    (vault / "shaft.prt").unlink()
    done = auth_client.post("/api/objects/batch/workspace", json={"object_ids": [objects["shaft.prt"]["uuid"]]})
    body = done.json()
    assert [item["filename"] for item in body["ok"]] == ["shaft.prt"] and body["skipped"] == []
    assert (vault / "shaft.prt").is_file()


def test_the_message_tells_the_user_why_nothing_was_copied():
    app = (ROOT / "src" / "creopdm" / "static" / "js" / "app.js").read_text(encoding="utf-8")
    body = app.split("const already = result.skipped?.length || 0;", 1)[1][:900]
    assert "already in the vault. Copy to Vault restores a working copy that was removed from it." in body
    assert "` already there.`" in body.replace(" ` already there.`", "` already there.`") or "already there." in body
    assert "Nothing to copy: select files" in body
