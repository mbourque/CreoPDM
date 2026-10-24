"""Right-click → Check out and check in…: modified files nobody holds, where the gates allow it."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
JS = ROOT / "src" / "creopdm" / "static" / "js"
NODE = shutil.which("node")


def _capabilities(state: dict) -> dict:
    script = (
        "global.window = global; global.document = {};"
        f"require({json.dumps(str(JS / 'files_context_menu.js'))});"
        f"const caps = window.CreoPdmFilesContextMenu.capabilities({json.dumps(state)});"
        "console.log(JSON.stringify(caps));"
    )
    done = subprocess.run([NODE, "-e", script], capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(done.stdout)


def _row(**kw):
    base = {
        "uuid": "u1", "filename": "plate.prt", "canCheckout": True, "owned": False, "canCheckin": False,
        "isNewFile": False, "isModifiedUnheld": True, "hasCheckinWork": False, "isFolder": False,
    }
    base.update(kw)
    return base


def _state(rows, **kw):
    state = {"rows": rows, "showCheckout": True, "showCheckin": True, "showOpen": True}
    state.update(kw)
    return state


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_offered_for_a_modified_file_nobody_holds():
    assert _capabilities(_state([_row()]))["canCheckoutCheckin"] is True
    assert _capabilities(_state([_row(), _row(uuid="u2")]))["canCheckoutCheckin"] is True  # several, all qualify


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_not_offered_when_the_gates_or_the_file_say_no():
    assert _capabilities(_state([_row()], showCheckout=False))["canCheckoutCheckin"] is False  # role / lifecycle
    assert _capabilities(_state([_row()], showCheckin=False))["canCheckoutCheckin"] is False
    assert _capabilities(_state([_row(canCheckout=False)]))["canCheckoutCheckin"] is False  # held by someone / released
    assert _capabilities(_state([_row(owned=True)]))["canCheckoutCheckin"] is False  # already checked out by me
    assert _capabilities(_state([_row(isModifiedUnheld=False)]))["canCheckoutCheckin"] is False  # not modified
    assert _capabilities(_state([_row(isNewFile=True)]))["canCheckoutCheckin"] is False  # new files use Add
    assert _capabilities(_state([_row(), _row(uuid="u2", isModifiedUnheld=False)]))["canCheckoutCheckin"] is False
    assert _capabilities(_state([_row()], busy=True))["canCheckoutCheckin"] is False
    assert _capabilities(_state([]))["canCheckoutCheckin"] is False


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_menu_is_shown_when_only_the_quick_action_is_available():
    script = (
        "global.window = global; global.document = {};"
        f"require({json.dumps(str(JS / 'files_context_menu.js'))});"
        "const api = window.CreoPdmFilesContextMenu;"
        "console.log(JSON.stringify([api.anyVisible({canCheckoutCheckin: true}), api.itemForAction('checkout-checkin').label]));"
    )
    done = subprocess.run([NODE, "-e", script], capture_output=True, text=True, encoding="utf-8", check=True)
    assert json.loads(done.stdout) == [True, "Check out and check in…"]


def test_the_page_and_the_navigator_wire_the_quick_action():
    app = (JS / "app.js").read_text(encoding="utf-8")
    assert "isModifiedUnheld: isModifiedNotCheckedOut(row)," in app
    assert 'if (action === "checkout-checkin") {' in app and app.count('"checkout-checkin"') >= 2
    chain = app.split("async function checkoutThenCheckinSelected() {", 1)[1].split("function filesContextMenuCapabilities", 1)[0]
    # both permissions are checked, the checkout is one batch call, then the normal Check In opens
    assert 'assertProductAllows(productId, "checkout")' in chain and 'assertProductAllows(productId, "checkin")' in chain
    assert "/api/objects/batch/checkout" in chain and "checkinBtn?.click()" in chain
    nav = (JS / "embed_explorer.js").read_text(encoding="utf-8")
    assert "isModifiedUnheld: Boolean(" in nav
    menu = (JS / "files_context_menu.js").read_text(encoding="utf-8")
    assert '"checkout-checkin": caps.canCheckoutCheckin,' in menu
