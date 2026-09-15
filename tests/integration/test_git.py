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
