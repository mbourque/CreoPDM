"""The Add file picker's file-type groups come from System Settings, not from fixed lists."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from creopdm.app import build_context, create_app
from creopdm.config import ConfigManager
from creopdm.utils.native_dialog import (
    add_files_dialog_filter_pairs,
    cad_dialog_filter_patterns,
    creo_model_dialog_filter_patterns,
)
from creopdm_agent.config import AgentConfig
from creopdm_agent.server import create_agent_app
from tests.conftest import requires_git
from tests.unit.test_baselines import _signed_in_admin

ROOT = Path(__file__).resolve().parents[2]


# ------------------------------------------------------------------ the dialog's groups
def test_creo_models_group_lists_every_configured_creo_model_extension():
    patterns = creo_model_dialog_filter_patterns([".prt", ".MFG", ".custom"]).split(";")
    assert "*.mfg" in patterns and "*.mfg.*" in patterns  # a configured .mfg shows up
    assert "*.custom" in patterns and "*.custom.*" in patterns
    assert "*.asm" not in patterns  # only what settings list


def test_cad_group_follows_the_three_cad_lists():
    patterns = cad_dialog_filter_patterns(models=[".mfg"], openable=[".sldprt"], extras=[".dat"]).split(";")
    assert {"*.mfg", "*.mfg.*", "*.*.mfg"} <= set(patterns)  # Creo models also get name.N.ext
    assert {"*.sldprt", "*.sldprt.*"} <= set(patterns) and "*.*.sldprt" not in patterns
    assert {"*.dat", "*.dat.*"} <= set(patterns)
    assert "*.prt" not in patterns  # a default that settings do not list


def test_all_four_groups_are_built_from_the_settings_lists():
    pairs = dict(
        add_files_dialog_filter_pairs(
            models=[".mfg"], openable=[".sldprt"], extras=[".dat"], documents=[".pdf", ".docx"]
        )
    )
    assert pairs["Creo models"] == "*.mfg;*.mfg.*"
    assert pairs["Documents"] == "*.pdf;*.docx"
    assert pairs["All files (*.*)"] == "*.*"
    assert "*.sldprt" in pairs["CAD files"]


# ------------------------------------------------------------------ the agent builds the dialog from the page's lists
def test_agent_passes_the_settings_lists_to_the_dialog(tmp_path, monkeypatch):
    root = tmp_path / "cache"
    root.mkdir()
    sample = tmp_path / "plant.mfg.1"
    sample.write_bytes(b"mfg")
    seen: dict = {}

    def fake_pick(initial_dir, title="Add files to the product", **kwargs):
        seen.update(kwargs)
        return [sample]

    app = create_agent_app(AgentConfig(host="127.0.0.1", port=8766, local_root=str(root)))
    monkeypatch.setattr("creopdm.utils.native_dialog.pick_files", fake_pick)
    with TestClient(app) as client:
        picked = client.post(
            "/pick-files",
            json={
                "initial_directory": str(tmp_path),
                "models": [".prt", ".MFG"],
                "openable": [".sldprt"],
                "extras": [".dat"],
                "documents": [".pdf"],
            },
        )
        assert picked.status_code == 200, picked.text
        assert seen["extensions"] == {
            "models": [".prt", ".mfg"],
            "openable": [".sldprt"],
            "extras": [".dat"],
            "documents": [".pdf"],
        }
        # Nothing sent (an older page): the dialog is not told anything, as before.
        seen.clear()
        assert client.post("/pick-files", json={"initial_directory": str(tmp_path)}).status_code == 200
        assert seen["extensions"] is None


# ------------------------------------------------------------------ the page sends them
@pytest.fixture()
def auth_ctx(data_dir):
    return build_context(ConfigManager())


@pytest.fixture()
def auth_client(auth_ctx):
    with TestClient(create_app(auth_ctx)) as client:
        yield client


@requires_git
def test_the_files_page_carries_the_settings_lists_for_the_picker(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    cad = auth_ctx.config.settings.cad
    cad.model_extensions = [".prt", ".mfg", ".zzmodel"]
    cad.openable_extensions = [".zzopen"]
    cad.extra_extensions = [".zzextra"]
    cad.document_extensions = [".zzdoc"]
    product = auth_client.post("/api/products", json={"name": "Picker"}).json()
    auth_client.post(
        f"/api/products/{product['uuid']}/objects",
        files={"file": ("a.prt", b"x", "application/octet-stream")},
        data={"comment": "x"},
    )
    html = auth_client.get(f"/?product={product['uuid']}").text

    def attr(name: str) -> list[str]:
        return html.split(f'{name}="', 1)[1].split('"', 1)[0].split(",")

    assert ".zzmodel" in attr("data-picker-models") and ".mfg" in attr("data-picker-models")
    assert attr("data-picker-openable") == [".zzopen"]
    assert attr("data-non-openable") == [".zzextra"]
    assert attr("data-documents") == [".zzdoc"]


def test_add_js_sends_the_lists_with_the_pick_request():
    js = (ROOT / "src/creopdm/static/js/add.js").read_text(encoding="utf-8")
    assert "function pickerExtensions()" in js
    for key in ("pickerModels", "pickerOpenable", "nonOpenable", "documents"):
        assert key in js
    # the Add pick (not the zip one) spreads them into the /pick-files body
    assert "...pickerExtensions()," in js
