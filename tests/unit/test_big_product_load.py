"""A big product must not make every page, poll and pane re-read everything (the Creo navigator polled
the whole 5 MB file list every 2 seconds)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

from creopdm.creo.file_manager import CreoFileManager
from creopdm.services.git_service import GitService, GitStatus
from creopdm.services.workspace_service import WorkspaceService
from tests.conftest import requires_git

ROOT = Path(__file__).resolve().parents[2]
JS = ROOT / "src" / "creopdm" / "static" / "js"


# ------------------------------------------------------------------ shared git status
class _FakeGit:
    def __init__(self):
        self.generation = 0
        self.calls = 0

    def is_repository(self, path):
        return True

    def status(self, path):
        self.calls += 1
        return GitStatus(branch="main", dirty=False, staged=[], unstaged=[], untracked=[], raw=f"run {self.calls}")


def _service(git, ttl):
    service = WorkspaceService.__new__(WorkspaceService)
    service._git = git
    service.vault_for = lambda product: Path("vault-a")
    service.STATUS_SHARE_SEC = ttl
    return service


def test_requests_that_arrive_together_share_one_git_status():
    git = _FakeGit()
    service = _service(git, ttl=30.0)
    product = SimpleNamespace(uuid="p")
    first = service._git_status(product, shared=True)
    second = service._git_status(product, shared=True)
    assert git.calls == 1 and first is second
    # not asked for sharing (a check-in decides from the live state): always runs git
    service._git_status(product)
    assert git.calls == 2


def test_a_git_command_that_changes_the_repository_ends_the_sharing():
    git = _FakeGit()
    service = _service(git, ttl=30.0)
    product = SimpleNamespace(uuid="p")
    service._git_status(product, shared=True)
    git.generation += 1  # what GitService does around add / commit / checkout ...
    service._git_status(product, shared=True)
    assert git.calls == 2


def test_sharing_can_be_turned_off():
    git = _FakeGit()
    service = _service(git, ttl=0.0)
    product = SimpleNamespace(uuid="p")
    service._git_status(product, shared=True)
    service._git_status(product, shared=True)
    assert git.calls == 2


def test_git_service_counts_only_commands_that_change_a_repository(monkeypatch, tmp_path):
    assert GitService._subcommand(["-c", "core.quotepath=false", "status", "--porcelain"]) == "status"
    assert GitService._subcommand(["commit", "-m", "x"]) == "commit"

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("creopdm.services.git_service.subprocess.run", fake_run)
    git = GitService()
    git._run(["status", "--porcelain"], cwd=tmp_path, check=False, quiet=True)
    assert git.generation == 0
    git._run(["add", "--", "a.prt"], cwd=tmp_path, check=False, quiet=True)
    assert git.generation == 2  # before and after
    git._run(["rev-parse", "HEAD"], cwd=tmp_path, check=False, quiet=True)
    assert git.generation == 2


def test_the_heavy_read_paths_ask_for_the_shared_status():
    checkout = (ROOT / "src" / "creopdm" / "api" / "checkout.py").read_text(encoding="utf-8")
    assert "ctx.workspaces._git_status(product, shared=True)" in checkout
    workspace = (ROOT / "src" / "creopdm" / "services" / "workspace_service.py").read_text(encoding="utf-8")
    watch = workspace.split("def watch_stamp(", 1)[1][:600]
    assert "shared=True" in watch


# ------------------------------------------------------------------ the folder lookup
def test_latest_save_in_a_big_folder_still_finds_the_newest_numbered_file(tmp_path):
    for index in range(300):
        (tmp_path / f"other{index:03d}.prt").write_bytes(b"x")
        (tmp_path / f"other{index:03d}.prt.2").write_bytes(b"x")
    (tmp_path / "shaft.prt").write_bytes(b"1")
    (tmp_path / "shaft.prt.2").write_bytes(b"2")
    (tmp_path / "shaft.prt.5").write_bytes(b"5")
    (tmp_path / "shaftbolt.prt").write_bytes(b"other")  # same prefix, another object
    found = CreoFileManager.latest_in_directory(tmp_path, "shaft.prt")
    assert found is not None and found.name == "shaft.prt.5"
    assert CreoFileManager.latest_in_directory(tmp_path, "missing.prt") is None
    plain = CreoFileManager.latest_in_directory(tmp_path, "shaftbolt.prt")
    assert plain is not None and plain.name == "shaftbolt.prt"


# ------------------------------------------------------------------ the stamp endpoint
def _add(client, product_uuid, name):
    added = client.post(
        f"/api/products/{product_uuid}/objects",
        files={"file": (name, f"{name}-v1".encode(), "application/octet-stream")},
        data={"comment": "x"},
    )
    assert added.status_code == 201, added.text
    return added.json()


@requires_git
def test_objects_stamp_is_steady_until_something_changes(client):
    product = client.post("/api/products", json={"name": "Stamp"}).json()
    shaft = _add(client, product["uuid"], "shaft.prt")
    url = f"/api/products/{product['uuid']}/objects-stamp"
    first = client.get(url)
    assert first.status_code == 200, first.text
    stamp = first.json()["stamp"]
    assert stamp and client.get(url).json()["stamp"] == stamp  # nothing changed: same stamp
    _add(client, product["uuid"], "gear.prt")
    after_add = client.get(url).json()["stamp"]
    assert after_add != stamp
    assert client.post(f"/api/objects/{shaft['uuid']}/checkout").status_code == 200
    assert client.get(url).json()["stamp"] != after_add  # a checkout moves it too


@requires_git
def test_objects_stamp_needs_a_product_you_can_open(client):
    assert client.get("/api/products/00000000-0000-4000-8000-000000000000/objects-stamp").status_code == 404


# ------------------------------------------------------------------ Details does not read the whole product
@requires_git
def test_details_page_is_built_without_loading_every_file(client, monkeypatch):
    product = client.post("/api/products", json={"name": "Detail"}).json()
    shaft = _add(client, product["uuid"], "shaft.prt")
    for index in range(5):
        _add(client, product["uuid"], f"part{index}.prt")
    import creopdm.services.object_service as object_service

    calls = []
    real = object_service.ObjectService.list_objects

    def counting(self, *args, **kwargs):
        calls.append(1)
        return real(self, *args, **kwargs)

    monkeypatch.setattr(object_service.ObjectService, "list_objects", counting)
    page = client.get(f"/products/{product['uuid']}/objects/{shaft['uuid']}")
    assert page.status_code == 200, page.text
    assert calls == []  # no full product load for one file's page


def test_the_details_route_uses_light_lookups():
    pages = (ROOT / "src" / "creopdm" / "api" / "pages.py").read_text(encoding="utf-8")
    detail = pages.split("def _object_detail_page(", 1)[1].split("\n@router", 1)[0]
    assert "list_objects(" not in detail
    assert "ctx.objects.list_path_index(db, product.id)" in detail
    assert "if bom or structure:" in detail  # the name lookup only when there is something to link
    index_fn = pages.split("def _product_bom_index(", 1)[1].split("def _enrich_bom_tree", 1)[0]
    assert "select(EngineeringObject.uuid, EngineeringObject.filename)" in index_fn
    assert "list_objects" not in index_fn


# ------------------------------------------------------------------ the navigator pane
def test_the_navigator_pane_asks_for_a_stamp_before_downloading_the_list():
    pane = (JS / "embed_explorer.js").read_text(encoding="utf-8")
    assert "var FOLLOW_POLL_MS = 5000;" in pane
    refresh = pane.split("async function refreshIfChanged() {", 1)[1].split("async function softRefreshList()", 1)[0]
    assert "listRefreshing" in refresh and "document.hidden" in refresh  # never two at once, none while hidden
    assert "stamp === lastListStamp" in refresh and "await softRefreshList();" in refresh
    stamp = pane.split("async function fetchListStamp() {", 1)[1].split("async function refreshIfChanged()", 1)[0]
    assert "/objects-stamp?_=" in stamp and "listAgentCacheFilesPreferringVault()" in stamp
    tick = pane.split("function startFollowActivePoll() {", 1)[1].split("async function openInMainEmbeddedBrowser", 1)[0]
    assert "refreshIfChanged()" in tick and "scheduleSoftRefresh(0)" not in tick


# ------------------------------------------------------------------ the Files page workspace poll
def _app_js() -> str:
    return (JS / "app.js").read_text(encoding="utf-8")


def test_the_product_list_is_downloaded_once_for_callers_that_ask_together():
    script = _app_js()
    ensure = script.split("async function ensureProductObjects(", 1)[1].split("async function countLocalWorkspacePending", 1)[0]
    assert "productObjectsInFlight" in ensure and "WORKSPACE_LIST_CACHE_MS" in ensure
    known = script.split("async function loadKnownWorkspacePaths(", 1)[1].split("async function ensureKnownWorkspacePaths", 1)[0]
    assert "ensureProductObjects(productId)" in known
    assert "/objects`" not in known  # no second full download of the list


def test_the_workspace_poll_compares_with_its_own_last_estimate():
    script = _app_js()
    poll = script.split("async function pollWorkspaceWatch() {", 1)[1].split("if (watchProductId) {", 1)[0]
    assert "lastPollChangesCount" in poll and "lastPollModifiedCount" in poll
    # not with the counts a confirmed queue load wrote (they can differ and re-trigger every poll)
    assert "lastChangesPending !== newCount" not in poll
    assert "lastModifiedPending !== modCount" not in poll


def test_slow_requests_name_the_page_that_asked():
    app_py = (ROOT / "src" / "creopdm" / "app.py").read_text(encoding="utf-8")
    assert 'request.headers.get("referer"' in app_py and "from=%s" in app_py


def test_a_page_load_reads_the_queue_and_the_list_once():
    script = _app_js()
    parts = script.split("async function loadCheckinQueueParts(", 1)[1].split("function prefetchCheckinQueueParts", 1)[0]
    assert "ensureProductObjects(productId, { maxAgeMs: 5000 })" in parts  # shared list, not its own download
    assert "/objects`" not in parts
    assert "{ skipQueue: true }" in parts  # the queue was just read: do not read it a second time
    known = script.split("async function loadKnownWorkspacePaths(", 1)[1].split("async function ensureKnownWorkspacePaths", 1)[0]
    assert "skipQueue" in known


def test_pending_id_refreshes_that_arrive_together_share_one_run():
    script = _app_js()
    wrapper = script.split("function refreshPendingCheckinIds(productId) {", 1)[1].split("async function refreshPendingCheckinIdsNow", 1)[0]
    assert "pendingCheckinIdsRun" in wrapper and "< 2000" in wrapper  # a later call still reads fresh data
