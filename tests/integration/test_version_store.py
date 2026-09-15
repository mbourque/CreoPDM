from pathlib import Path

from creopdm.services.git_service import GitService
from creopdm.storage.git_store import GitVersionStore
from creopdm.utils.identity import UserIdentity
from tests.conftest import requires_git


@requires_git
def test_version_store_roundtrip(tmp_path: Path):
    repo = tmp_path / "repo"
    git = GitService()
    git.init_repository(repo)
    (repo / "CAD").mkdir()
    target = repo / "CAD" / "shaft.prt"
    target.write_bytes(b"v1")
    store = GitVersionStore(git)
    author = UserIdentity("bob", "ENG-PC-17")
    ref = store.store_version(repo, ["CAD/shaft.prt"], "Initial model", author)
    assert store.get_version(repo, "CAD/shaft.prt", ref) == b"v1"
    history = store.get_history(repo, "CAD/shaft.prt")
    assert history[0].version_ref == ref
