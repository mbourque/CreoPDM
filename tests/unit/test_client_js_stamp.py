"""A deploy changes /client/app.js?v=… so soft-nav swaps in the new script (no hard reload)."""

from pathlib import Path

from creopdm.client_stamp import CLIENT_JS_STAMP, compute_client_js_stamp
from tests.conftest import requires_git

ROOT = Path(__file__).resolve().parents[2]


def test_stamp_follows_the_content_of_the_client_scripts(tmp_path):
    (tmp_path / "app.js").write_text("const a = 1;\n", encoding="utf-8")
    (tmp_path / "checkout.js").write_text("const b = 2;\n", encoding="utf-8")
    first = compute_client_js_stamp(tmp_path)
    assert first == compute_client_js_stamp(tmp_path)  # stable while nothing changes
    (tmp_path / "checkout.js").write_text("const b = 3;\n", encoding="utf-8")
    second = compute_client_js_stamp(tmp_path)
    assert second != first  # a lazy module change alone flips it
    (tmp_path / "new_module.js").write_text("const c = 1;\n", encoding="utf-8")
    assert compute_client_js_stamp(tmp_path) != second  # so does a new module
    assert len(first) == 10


def test_stamp_is_safe_when_there_are_no_scripts(tmp_path):
    assert compute_client_js_stamp(tmp_path) == "0"
    assert compute_client_js_stamp(tmp_path / "missing") == "0"


def test_the_shipped_scripts_have_a_real_stamp():
    assert CLIENT_JS_STAMP not in {"", "0"}


def test_base_template_puts_the_stamp_on_the_app_script_url():
    base = (ROOT / "src" / "creopdm" / "templates" / "base.html").read_text(encoding="utf-8")
    assert "/client/app.js?v={{ app_version }}-no-product-readonly-{{ client_js_stamp" in base


@requires_git
def test_rendered_page_carries_the_current_stamp(client):
    page = client.get("/")
    assert page.status_code == 200, page.text
    assert f"-no-product-readonly-{CLIENT_JS_STAMP}" in page.text
