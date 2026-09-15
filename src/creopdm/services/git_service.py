"""Subprocess Git wrapper. No other module should invoke Git directly."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from creopdm.exceptions import RepositoryError
from creopdm.logging_setup import get_logger
from creopdm.utils.identity import UserIdentity

logger = get_logger("git")


@dataclass(frozen=True, slots=True)
class GitStatus:
    branch: str
    dirty: bool
    staged: list[str]
    unstaged: list[str]
    untracked: list[str]


@dataclass(frozen=True, slots=True)
class GitHistoryEntry:
    commit_hash: str
    author: str
    message: str
    timestamp: str


class GitRemote:
    """Generic remote. GitHub/GitLab/etc. are URLs, not special-cased providers."""

    def __init__(self, name: str, url: str, provider: str = "generic") -> None:
        self.name = name
        self.url = url
        self.provider = provider


class GitService:
    """Small explicit Git abstraction using argument arrays, never shell=True."""

    def __init__(self, executable: str = "git") -> None:
        self.executable = executable or "git"

    def _run(
        self,
        args: list[str],
        cwd: Path,
        check: bool = True,
        extra_env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        command = [self.executable, *args]
        logger.info("git %s", " ".join(args))
        try:
            result = subprocess.run(
                command,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                check=False,
                shell=False,
                env=extra_env,
            )
        except FileNotFoundError as exc:
            raise RepositoryError(
                "Git is not installed or is not on PATH.",
                details={"executable": self.executable},
            ) from exc
        if check and result.returncode != 0:
            message = (result.stderr or result.stdout or "Git command failed").strip()
            logger.error("Git failure: %s", message)
            raise RepositoryError(message, details={"args": args})
        return result

    def is_available(self) -> bool:
        try:
            result = subprocess.run(
                [self.executable, "--version"],
                capture_output=True,
                text=True,
                check=False,
                shell=False,
            )
        except FileNotFoundError:
            return False
        return result.returncode == 0

    def is_repository(self, path: Path) -> bool:
        return (path / ".git").exists()

    def ensure_repository(self, path: Path, default_branch: str = "main") -> None:
        """Create Git metadata if it is missing. Existing files are left untouched."""
        if self.is_repository(path):
            return
        logger.warning(
            "Git metadata missing at %s; initializing a new repository without deleting files.",
            path,
        )
        self.init_repository(path, default_branch)

    def init_repository(self, path: Path, default_branch: str = "main") -> None:
        path.mkdir(parents=True, exist_ok=True)
        if (path / ".git").exists():
            logger.info("Repository already initialized at %s", path)
            return
        result = self._run(["init", "-b", default_branch], cwd=path, check=False)
        if result.returncode != 0:
            self._run(["init"], cwd=path)
            current = self._run(["rev-parse", "--abbrev-ref", "HEAD"], cwd=path, check=False)
            branch = (current.stdout or "").strip()
            if branch and branch != default_branch and branch != "HEAD":
                self._run(["branch", "-M", default_branch], cwd=path, check=False)
            elif branch == "HEAD":
                # Empty repo: set the initial branch name for the first commit.
                self._run(["symbolic-ref", "HEAD", f"refs/heads/{default_branch}"], cwd=path)

    def status(self, path: Path) -> GitStatus:
        branch_result = self._run(["rev-parse", "--abbrev-ref", "HEAD"], cwd=path, check=False)
        branch = (branch_result.stdout or "main").strip() or "main"
        porcelain = self._run(["status", "--porcelain"], cwd=path)
        staged: list[str] = []
        unstaged: list[str] = []
        untracked: list[str] = []
        for line in porcelain.stdout.splitlines():
            if not line:
                continue
            code = line[:2]
            file_name = line[3:]
            if code == "??":
                untracked.append(file_name)
            else:
                if code[0] not in (" ", "?"):
                    staged.append(file_name)
                if code[1] not in (" ", "?"):
                    unstaged.append(file_name)
        return GitStatus(
            branch=branch,
            dirty=bool(staged or unstaged or untracked),
            staged=staged,
            unstaged=unstaged,
            untracked=untracked,
        )

    def is_dirty(self, path: Path) -> bool:
        return self.status(path).dirty

    def stage_files(self, path: Path, files: list[str]) -> None:
        if not files:
            return
        self._run(["add", "--", *files], cwd=path)

    def remove_files(self, path: Path, files: list[str], *, keep_working_copy: bool = False) -> None:
        if not files:
            return
        args = ["rm", "-f", "--ignore-unmatch"]
        if keep_working_copy:
            args.append("--cached")
        self._run([*args, "--", *files], cwd=path)

    def commit(
        self,
        path: Path,
        message: str,
        author: UserIdentity,
        allow_empty: bool = False,
    ) -> str:
        if not message.strip():
            raise RepositoryError("A commit comment is required.")
        args = ["commit", "-m", message]
        if allow_empty:
            args.append("--allow-empty")
            # Isolate author identity without writing credentials or relying on global git config.
        result = self._run(
            [
                "-c",
                f"user.name={author.user_name}",
                "-c",
                f"user.email={author.user_name}@creopdm.local",
                *args,
            ],
            cwd=path,
        )
        logger.debug("commit stdout: %s", result.stdout)
        return self.get_head(path)

    def get_head(self, path: Path) -> str:
        result = self._run(["rev-parse", "HEAD"], cwd=path)
        return result.stdout.strip()

    def get_history(self, path: Path, relative_path: str | None = None, limit: int = 50) -> list[GitHistoryEntry]:
        args = ["log", f"-n{limit}", "--format=%H%x1f%an%x1f%s%x1f%cI"]
        if relative_path:
            args.extend(["--", relative_path])
        result = self._run(args, cwd=path, check=False)
        if result.returncode != 0:
            return []
        entries: list[GitHistoryEntry] = []
        for line in result.stdout.splitlines():
            parts = line.split("\x1f")
            if len(parts) != 4:
                continue
            commit_hash, author, message, timestamp = parts
            entries.append(
                GitHistoryEntry(
                    commit_hash=commit_hash,
                    author=author,
                    message=message,
                    timestamp=timestamp,
                )
            )
        return entries

    def restore_file(self, path: Path, relative_path: str, commit_hash: str) -> None:
        self._run(["checkout", commit_hash, "--", relative_path], cwd=path)

    def show_file(self, path: Path, relative_path: str, commit_hash: str) -> bytes:
        posix = relative_path.replace("\\", "/")
        result = subprocess.run(
            [self.executable, "show", f"{commit_hash}:{posix}"],
            cwd=str(path),
            capture_output=True,
            check=False,
            shell=False,
        )
        if result.returncode != 0:
            raise RepositoryError(
                "Unable to read stored version.",
                details={"path": relative_path},
            )
        return result.stdout

    def add_remote(self, path: Path, remote: GitRemote) -> None:
        existing = self._run(["remote"], cwd=path)
        names = {line.strip() for line in existing.stdout.splitlines() if line.strip()}
        if remote.name in names:
            self._run(["remote", "set-url", remote.name, remote.url], cwd=path)
        else:
            self._run(["remote", "add", remote.name, remote.url], cwd=path)

    def remove_remote(self, path: Path, name: str) -> None:
        self._run(["remote", "remove", name], cwd=path)

    def fetch(self, path: Path, remote: str = "origin") -> None:
        self._run(["fetch", remote], cwd=path)

    def pull(self, path: Path, remote: str = "origin", branch: str = "main") -> None:
        self._run(["pull", remote, branch], cwd=path)

    def push(self, path: Path, remote: str = "origin", branch: str = "main") -> None:
        self._run(["push", remote, branch], cwd=path)

    def reset_to(self, path: Path, commit_hash: str) -> None:
        """Restore repository HEAD after a failed metadata transaction. Hard reset is reserved for recovery."""
        logger.warning("Restoring repository HEAD to %s", commit_hash)
        self._run(["reset", "--hard", commit_hash], cwd=path)
