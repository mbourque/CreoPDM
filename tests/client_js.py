"""Read the Files-page client bundle: app.js shell plus lazy feature modules.

`app.js` keeps boot, selection, toolbar sync, and small lazy-load wrappers.
Feature bodies live under ``static/js/`` and load via ``ensureModule(name)``:

- ``admin.js`` — Settings / Admin chrome
- ``add.js`` — Add dialog, pickers, drops, compressed import
- ``modifications.js`` — Ask AI / Modifications / history revert
- ``metadata.js`` — Collect job, Where Used index / Rebuild
- ``creo_workspace.js`` — Creo session gather/push + agent materialize
- ``open.js`` — Open chooser, prepare, File > Open trail
- ``checkout.js`` — Checkout / Undo / Force Undo
- ``checkin.js`` — Check In / Add selected dialog + submit

Folder list, selection, ``syncToolbar``, and metrics stay in ``app.js``
(too coupled for a ``files.js`` split).

Contract tests that only care that a string still ships to the browser use
``client_js_bundle()``. Tests that slice one function with ``_between`` should
read the module file that owns that function.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS_DIR = ROOT / "src" / "creopdm" / "static" / "js"

APP_JS = JS_DIR / "app.js"
ADMIN_JS = JS_DIR / "admin.js"
ADD_JS = JS_DIR / "add.js"
MODIFICATIONS_JS = JS_DIR / "modifications.js"
METADATA_JS = JS_DIR / "metadata.js"
CREO_WORKSPACE_JS = JS_DIR / "creo_workspace.js"
OPEN_JS = JS_DIR / "open.js"
CHECKOUT_JS = JS_DIR / "checkout.js"
CHECKIN_JS = JS_DIR / "checkin.js"

# app.js first so `_between` start markers keep resolving to the shell wrappers
# unless the marker only exists in a feature module.
CLIENT_JS_FILES = (
    APP_JS,
    ADMIN_JS,
    ADD_JS,
    MODIFICATIONS_JS,
    METADATA_JS,
    CREO_WORKSPACE_JS,
    OPEN_JS,
    CHECKOUT_JS,
    CHECKIN_JS,
)


def client_js_bundle() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in CLIENT_JS_FILES)


class ClientJsResponse:
    """`client.get('/static/js/app.js')` plus lazy modules (status/headers from the real GET)."""

    def __init__(self, response) -> None:
        self.status_code = response.status_code
        self.headers = response.headers
        self.text = response.text + "\n" + "\n".join(
            path.read_text(encoding="utf-8") for path in CLIENT_JS_FILES[1:]
        )


def app_js_with_modules(response) -> ClientJsResponse:
    return ClientJsResponse(response)
