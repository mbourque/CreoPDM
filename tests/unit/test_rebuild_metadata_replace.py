"""Rebuild replaces each model's metadata when its read succeeds; an unreadable model keeps what it had."""

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


def _post(auth_client, obj, **body):
    posted = auth_client.post(f"/api/objects/{obj['uuid']}/creo-metadata", json=body)
    assert posted.status_code == 200, posted.text
    return posted.json()


def _get(auth_client, obj):
    return auth_client.get(f"/api/objects/{obj['uuid']}/creo-metadata").json()


@requires_git
def test_a_replace_save_drops_what_the_new_read_no_longer_has(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    _product_row, objects = _product(auth_client, "Gearbox")
    shaft = objects["shaft.prt"]
    _post(
        auth_client, shaft,
        identity={"model_type": "PART", "common_name": "Shaft"},
        parameters=[{"name": "DIAMETER", "value": "25"}, {"name": "OLD_PARAM", "value": "1"}],
        mass={"mass": 4.2},
        materials={"current": "STEEL", "available": ["STEEL"]},
    )
    # A merge (the normal save) keeps what the new read does not mention ...
    merged = _post(auth_client, shaft, identity={"model_type": "PART", "common_name": "Shaft"},
                   parameters=[{"name": "DIAMETER", "value": "30"}])
    assert merged["mass"] == {"mass": 4.2} and merged["materials"]["current"] == "STEEL"
    # ... a Rebuild save replaces: the mass, material and the parameter that are gone leave with it.
    replaced = _post(auth_client, shaft, replace=True, identity={"model_type": "PART", "common_name": "Shaft"},
                     parameters=[{"name": "DIAMETER", "value": "35"}])
    assert replaced["mass"] is None and replaced["materials"] is None
    assert [(p["name"], p["value"]) for p in replaced["parameters"]] == [("DIAMETER", "35")]


@requires_git
def test_an_unread_model_keeps_its_metadata_because_nothing_is_wiped_up_front(auth_client, auth_ctx):
    """The server only changes a version when a save arrives; Rebuild sends none for a failed read."""
    _signed_in_admin(auth_client, auth_ctx)
    _p, objects = _product(auth_client, "Gearbox")
    shaft, gear = objects["shaft.prt"], objects["gear.prt"]
    for obj in (shaft, gear):
        _post(auth_client, obj, identity={"model_type": "PART", "common_name": obj["filename"]},
              parameters=[{"name": "P", "value": "1"}])
    _post(auth_client, shaft, replace=True, identity={"model_type": "PART", "common_name": "Shaft v2"})
    assert _get(auth_client, shaft)["identity"]["common_name"] == "Shaft v2"
    assert _get(auth_client, gear)["identity"]["common_name"] == "gear.prt"  # untouched
    assert [p["name"] for p in _get(auth_client, gear)["parameters"]] == ["P"]


def test_rebuild_replaces_per_model_retries_and_names_what_could_not_be_read():
    meta = (ROOT / "src" / "creopdm" / "static" / "js" / "metadata.js").read_text(encoding="utf-8")
    run = meta.split("async function runCollectAllMetadata", 1)[1].split("async function runRebuildAllMetadata", 1)[0]
    assert "clear-creo-metadata" not in run and "replace: rebuild," in run
    assert "if (opts.replace) body.replace = true;" in meta
    assert "replace: Boolean(state.replace)," in meta
    # one more read for the failures before the finish line, then they are named
    assert "Reading failed files again…" in meta
    assert "`${unreadable} could not be read`" in meta and "noteCollectFailures(failedFiles, false)" in meta
    assert "A model that cannot be read keeps its previous metadata." in meta
    page = (ROOT / "src" / "creopdm" / "templates" / "app.html").read_text(encoding="utf-8")
    assert "a model that cannot be read keeps what it had" in page
