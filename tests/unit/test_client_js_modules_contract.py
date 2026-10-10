"""Contract: app.js feature split (lazy classic-script modules under static/js/).

Locks:
- big feature bodies live in modules, not in app.js
- app.js keeps thin lazy wrappers (ensureModule via initJobModule)
- every ``shell.X`` a module reads exists on ``window.__creopdmShell``
- quiet Files browse does not eagerly load modifications/add/open/metadata/creo_workspace
"""

from __future__ import annotations

import re

from tests.client_js import (
    ADD_JS,
    ADMIN_JS,
    APP_JS,
    CREO_WORKSPACE_JS,
    METADATA_JS,
    MODIFICATIONS_JS,
    OPEN_JS,
)

MODULES = {
    "admin": ADMIN_JS,
    "add": ADD_JS,
    "modifications": MODIFICATIONS_JS,
    "metadata": METADATA_JS,
    "creo_workspace": CREO_WORKSPACE_JS,
    "open": OPEN_JS,
}

# Large bodies that must not live in app.js any more (wrappers are single-line delegates).
MOVED_OUT_OF_APP = (
    "async function runMetadataCollectLoop(",
    "async function pushOneCreoMetadataTarget(",
    "async function runCollectAllMetadata(",
    "function confirmCollectMetadata(",
    "async function awaitWhereUsedIndex(productId, { onProgress",
    "function watchWhereUsedIndex(",
    "async function materializeViaAgentPerFile(",
    "async function materializeCheckedOutToAgentCacheZip(",
    "function cachePlanItemsFromPrepared(",
    "async function openPdmObjectWork(",
    "async function openLocalCacheRelative(",
    "function promptOpenCheckout(",
    "async function checkoutBeforeOpen(",
    "async function openViaAgent(",
    "function openPdmLaunchResult(",
    "function metadataItemsFromOpenResult(",
)


def _shell_keys(app_text: str) -> set[str]:
    start = app_text.index("window.__creopdmShell = {")
    end = app_text.index("\n  };", start)
    body = app_text[start:end]
    keys = set(re.findall(r"^\s{4}(?:get\s+)?(\w+)\s*(?:[,:(])", body, flags=re.MULTILINE))
    return keys


def test_modules_register_and_export_init():
    for name, path in MODULES.items():
        text = path.read_text(encoding="utf-8")
        assert f"window.__creopdmModules.{name}" in text, name
        assert "init(shell)" in text, name


def test_feature_bodies_left_app_js():
    app = APP_JS.read_text(encoding="utf-8")
    for marker in MOVED_OUT_OF_APP:
        assert marker not in app, f"{marker!r} should live in a lazy module"
    # Wrappers stay.
    for wrapper in (
        "async function indexWhereUsedUnderBusy(",
        "async function resumeMetadataCollectIfNeeded(",
        "async function openPdmObject(",
        "async function openPdmObjectFromUi(",
        "async function materializeViaAgent(",
        "async function pushCreoMetadataForItems(",
    ):
        assert wrapper in app, wrapper
    assert 'initJobModule("metadata")' in app
    assert 'initJobModule("open")' in app
    assert 'initJobModule("creo_workspace")' in app


def test_modules_only_read_shell_members_that_exist():
    app = APP_JS.read_text(encoding="utf-8")
    keys = _shell_keys(app)
    assert {"withBusy", "showError", "currentProductId"} <= keys
    for name, path in MODULES.items():
        text = path.read_text(encoding="utf-8")
        used = set(re.findall(r"\bshell\.(\w+)", text))
        for block in re.findall(r"const\s*\{([^}]*)\}\s*=\s*shell\b", text):
            for part in block.split(","):
                member = part.split(":", 1)[0].split("=", 1)[0].strip()
                if member.startswith("//") or not re.fullmatch(r"\w+", member):
                    continue
                used.add(member)
        missing = sorted(item for item in used if item not in keys)
        assert not missing, f"{name}.js reads shell members missing from app.js: {missing}"


def test_quiet_browse_does_not_eager_load_heavy_modules():
    app = APP_JS.read_text(encoding="utf-8")
    boot_tail = app.split("window.__creopdmShell = {", 1)[1]
    boot_tail = boot_tail.split("restoreStoredFilters();", 1)[1]
    # Only admin chrome + modifications (Details) are initialised eagerly at boot.
    eager = re.findall(r'void initJobModule\("(\w+)"', boot_tail.split("} finally {", 1)[0])
    assert set(eager) <= {"admin", "modifications"}, eager
    # Collect resume is gated on stored state; open/add/creo_workspace load on use.
    assert "const state = loadMetadataCollectState();" in app
    assert 'if (!state || state.status !== "running")' in app


def test_open_module_keeps_large_assembly_contract():
    text = OPEN_JS.read_text(encoding="utf-8")
    assert "creoOpenModelTimeoutMs(preparedDependencyCount(prepared))" in text
    assert "openWorkTimeoutMs(5000)" in text
    assert "90000" not in text
    assert "if (wantSetWd)" in text
