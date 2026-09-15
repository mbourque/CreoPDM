from pathlib import Path

from creopdm.services.git_service import GitService
from creopdm.utils.identity import UserIdentity
from tests.conftest import requires_git


@requires_git
def test_git_commit_and_history(tmp_path: Path):
    repo = tmp_path / "repo"
    git = GitService()
    git.init_repository(repo, "main")
    (repo / "README.md").write_text("hello", encoding="utf-8")
    git.stage_files(repo, ["README.md"])
    author = UserIdentity(user_name="tester", machine_name="test-pc")
    commit = git.commit(repo, "Initial files", author)
    assert len(commit) >= 7
    history = git.get_history(repo)
    assert history[0].commit_hash == commit
    assert history[0].message == "Initial files"
    assert git.get_head(repo) == commit
    assert git.is_dirty(repo) is False


@requires_git
def test_clone_into_preserves_history(tmp_path: Path):
    source = tmp_path / "source"
    git = GitService()
    git.init_repository(source, "main")
    (source / "pin.prt").write_bytes(b"part")
    git.stage_files(source, ["pin.prt"])
    author = UserIdentity(user_name="tester", machine_name="test-pc")
    commit = git.commit(source, "Add pin", author)

    empty = tmp_path / "empty"
    git.clone_into(source, empty)
    assert git.is_repository(empty)
    assert git.get_head(empty) == commit
    assert (empty / "pin.prt").read_bytes() == b"part"

    populated = tmp_path / "populated"
    populated.mkdir()
    (populated / "keep.dat").write_bytes(b"local")
    git.clone_into(source, populated)
    assert git.is_repository(populated)
    assert git.get_head(populated) == commit
    assert (populated / "pin.prt").read_bytes() == b"part"
    assert (populated / "keep.dat").read_bytes() == b"local"
    assert not (tmp_path / "populated.git-migrate").exists()
