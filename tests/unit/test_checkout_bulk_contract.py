"""Checkout product stays on the bulk path (light list, one git status, agent hash plan)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "creopdm"


def _read(*parts: str) -> str:
    return SRC.joinpath(*parts).read_text(encoding="utf-8")


def test_checkout_product_uses_light_id_list_not_files_presentation():
    js = _read("static", "js", "checkout.js")
    start = js.index("async function checkoutProduct()")
    body = js[start : js.index("async function undoCheckout()")]
    assert "/checkoutable-ids" in body
    # Regression: this used to GET the full /objects presentation (git status, labels,
    # per-row hash checks for every file) just to read can_checkout flags.
    assert "/objects`" not in body


def test_checkout_passes_response_identities_to_the_agent_plan():
    """Identities let the agent use .creopdm_cache_index.json (stat only) — no manifest fetch."""
    js = _read("static", "js", "checkout.js")
    assert "plan_items" in js
    assert "planItems" in js
    ws = _read("static", "js", "creo_workspace.js")
    assert (
        "async function materializeCheckedOutToAgentCacheZip(objectIds, prepared, identities)" in ws
    )
    assert "options.planItems" in ws
    app_js = _read("static", "js", "app.js")
    assert (
        "async function materializeCheckedOutToAgentCache(objectIds, onProgress, options)" in app_js
    )


def test_checkout_many_is_bulk_not_per_file_checkout():
    service = _read("services", "checkout_service.py")
    start = service.index("def checkout_many(")
    body = service[start : service.index("def _checkout_group(")]
    assert "self.checkout(session" not in body
    group = service[service.index("def _checkout_group(") : service.index("def _new_checkout_row(")]
    assert "checkout_workspace_context" in group
    assert "_insert_checkouts" in group


def test_materialize_skips_second_hash_when_workspace_is_the_vault():
    workspace = _read("services", "workspace_service.py")
    start = workspace.index("    def materialize(")
    body = workspace[start : workspace.index("    def checkout_workspace_context(")]
    same_path = body.index("source.resolve() == destination.resolve()")
    second_hash = body.index("not self._file_modified(destination, obj)")
    assert same_path < second_hash
