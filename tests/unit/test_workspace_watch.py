from types import SimpleNamespace

from creopdm.constants import DEFAULT_CREO_MODEL_EXTENSIONS, DEFAULT_IGNORE_PATTERNS
from creopdm.services.git_service import GitStatus
from creopdm.services.workspace_service import WorkspaceService


class _Config:
    def all_cad_extensions(self):
        return list(DEFAULT_CREO_MODEL_EXTENSIONS)

    def ignore_patterns(self):
        return list(DEFAULT_IGNORE_PATTERNS)


def _status(*, staged=None, unstaged=None, untracked=None, raw=""):
    staged = list(staged or [])
    unstaged = list(unstaged or [])
    untracked = list(untracked or [])
    return GitStatus(
        branch="main",
        dirty=bool(staged or unstaged or untracked),
        staged=staged,
        unstaged=unstaged,
        untracked=untracked,
        raw=raw or "\n".join(untracked),
    )


def _watch(status, known=None):
    service = WorkspaceService(_Config())
    service._git_status = lambda project: status
    return service.watch_stamp(SimpleNamespace(uuid="project"), known)


def test_watch_stamp_counts_numbered_creo_save_as_pending():
    result = _watch(
        _status(untracked=["shaft.prt.2"], raw="?? shaft.prt.2"),
        [("shaft.prt", "shaft.prt")],
    )
    assert result["pending_saves"] == 1
    assert result["new_files"] == 0


def test_watch_stamp_counts_unknown_untracked_as_new_file():
    result = _watch(
        _status(untracked=["bushing.prt"], raw="?? bushing.prt"),
        [("shaft.prt", "shaft.prt")],
    )
    assert result["pending_saves"] == 0
    assert result["new_files"] == 1


def test_watch_stamp_ignores_creo_session_junk():
    result = _watch(
        _status(untracked=["trail.txt.5", "shaft.prt.2"], raw="?? trail.txt.5\n?? shaft.prt.2"),
        [("shaft.prt", "shaft.prt")],
    )
    assert result["pending_saves"] == 1
    assert result["new_files"] == 0


def test_watch_stamp_counts_unstaged_edit_of_known_file():
    result = _watch(
        _status(unstaged=["shaft.prt"], raw=" M shaft.prt"),
        [("shaft.prt", "shaft.prt")],
    )
    assert result["pending_saves"] == 1
    assert result["new_files"] == 0


def test_watch_stamp_does_not_count_older_numbered_save():
    result = _watch(
        _status(untracked=["shaft.prt.2"], raw="?? shaft.prt.2"),
        [("shaft.prt.3", "shaft.prt.3")],
    )
    assert result["pending_saves"] == 0
    assert result["new_files"] == 0


def test_watch_stamp_matches_nested_numbered_save():
    result = _watch(
        _status(untracked=["Incoming/lib/pin.prt.4"], raw="?? Incoming/lib/pin.prt.4"),
        [("Incoming/lib/pin.prt", "pin.prt")],
    )
    assert result["pending_saves"] == 1
    assert result["new_files"] == 0


def test_watch_stamp_changes_when_git_raw_changes():
    known = [("shaft.prt", "shaft.prt")]
    before = _watch(_status(raw=""), known)
    after = _watch(_status(untracked=["shaft.prt.2"], raw="?? shaft.prt.2"), known)
    assert after["stamp"] != before["stamp"]
    assert after["pending_saves"] == 1


def test_import_relative_path_nests_under_parent_folder(tmp_path):
    """Add Folder while in a Files subfolder must prefix with that location."""
    service = WorkspaceService(_Config())
    kit = tmp_path / "Kit"
    kit.mkdir()
    part = kit / "top.prt"
    part.write_bytes(b"top")
    project = SimpleNamespace(uuid="p1")
    assert service.import_relative_path(project, part, kit) == "Kit/top.prt"
    assert (
        service.import_relative_path(project, part, kit, parent_folder="Incoming")
        == "Incoming/Kit/top.prt"
    )
    assert (
        service.import_relative_path(project, part, None, parent_folder="Incoming")
        == "Incoming/top.prt"
    )
