"""Hard contract: product lock stays in product_state — UI + services cannot drift."""

from __future__ import annotations

from pathlib import Path

from creopdm.product_state import ProductUiCapabilities

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "creopdm"

# Services / API modules that perform vault or product mutations must call ensure_*.
_MUTATION_MODULES = (
    SRC / "services" / "object_service.py",
    SRC / "services" / "checkout_service.py",
    SRC / "services" / "checkin_service.py",
    SRC / "services" / "workspace_service.py",
    SRC / "services" / "metadata_service.py",
    SRC / "services" / "product_service.py",
    SRC / "api" / "products.py",
)

_APP_HTML = SRC / "templates" / "app.html"
_DETAIL_HTML = SRC / "templates" / "object_detail.html"
_APP_JS = SRC / "static" / "js" / "app.js"
_PAGES = SRC / "api" / "pages.py"


def test_mutation_modules_call_ensure_product_gate():
    """Forget ensure_* on a mutation path → this fails (security is not UI hide)."""
    for path in _MUTATION_MODULES:
        text = path.read_text(encoding="utf-8")
        assert path.is_file(), path
        assert (
            "ensure_product_mutable" in text or "ensure_product_deletable" in text
        ), f"{path.relative_to(ROOT)} must call ensure_product_mutable/deletable"


def test_pages_render_injects_product_ui():
    text = _PAGES.read_text(encoding="utf-8")
    assert "product_ui_capabilities" in text
    assert 'payload["product_ui"]' in text or "payload['product_ui']" in text


def test_templates_gate_toolbar_via_product_ui_only():
    """No scattered selected.allows_mutation / can_* ∩ allows_mutation in Files chrome."""
    app = _APP_HTML.read_text(encoding="utf-8")
    detail = _DETAIL_HTML.read_text(encoding="utf-8")
    for flag in (
        "show_add",
        "show_checkout",
        "show_checkin",
        "show_remove",
        "show_remove_vault",
        "show_remove_product",
        "show_rename",
        "show_delete_product",
        "show_metadata_tools",
        "show_access_banner",
    ):
        assert f"product_ui.{flag}" in app, f"app.html missing product_ui.{flag}"
    assert "product_ui.show_revert" in detail
    assert "product_ui.show_remove_vault" in detail
    assert "selected.allows_mutation" not in app
    assert "can_add_objects and" not in app
    assert "can_checkin and" not in app
    assert "can_update_metadata and" not in app
    assert "data-requires-mutation" not in app


def test_app_js_does_not_reencode_product_lock():
    script = _APP_JS.read_text(encoding="utf-8")
    assert "function productAllowsMutation" not in script
    assert "function mutationActionAllowed" not in script
    # Selection-only syncToolbar — no mutable && product-lock ANDs.
    sync = script.split("function syncToolbar(", 1)[1].split("function setCheckinQueueCounts(", 1)[0]
    assert "mutable &&" not in sync
    assert "allowsMutation" not in sync


def test_product_ui_capability_fields_stay_wired():
    """New ProductUiCapabilities field without a template reference is a smell — list stays explicit."""
    fields = {f.name for f in ProductUiCapabilities.__dataclass_fields__.values()}
    expected = {
        "allows_mutation",
        "show_access_banner",
        "show_add",
        "show_checkout",
        "show_checkin",
        "show_remove",
        "show_remove_vault",
        "show_remove_product",
        "show_rename",
        "show_delete_product",
        "show_metadata_tools",
        "show_revert",
    }
    assert fields == expected
