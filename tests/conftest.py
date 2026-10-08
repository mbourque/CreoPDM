from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from creopdm.app import build_context, create_app
from creopdm.config import ConfigManager
from creopdm.services.git_service import GitService
from creopdm.utils.identity import StaticUserProvider
from tests.pytest_basetemp import cleanup_stale_pytest_tmp

PYTEST_LAST_LOG = "pytest-last.log"


def pytest_configure(config):
    """Keep pytest temps in the repo. Windows often locks %TEMP%\\pytest-of-*."""
    root = Path(config.rootpath)
    inv_dir = root / "src" / "creopdm" / "static" / "creo_inventory"
    inv_marker = inv_dir / "features.creojs"
    wrap_script = root / "scripts" / "wrap_creo_inventory.py"
    if wrap_script.is_file() and not inv_marker.is_file():
        subprocess.run(
            [sys.executable, str(wrap_script)],
            cwd=str(root),
            check=True,
        )
    # Always scrub leftovers before any test collection/run. Locked Windows DBs
    # may survive one attempt; the next pytest run retries.
    cleanup_stale_pytest_tmp(root)
    configured = getattr(config.option, "basetemp", None)
    # pyproject used to force --basetemp=pytest-tmp; that shared tree gets stuck
    # on locked creopdm.db (WinError 32) and fails every following run's setup.
    if not configured or Path(str(configured)).name == "pytest-tmp":
        stamp = f"{os.getpid()}-{int(time.time())}"
        base = root / f"pytest-tmp-{stamp}"
        config.option.basetemp = str(base)


def pytest_sessionfinish(session, exitstatus):
    """Drop this run's basetemp when possible so the tree does not pile up."""
    root = Path(session.config.rootpath)
    configured = getattr(session.config.option, "basetemp", None)
    if configured:
        base = Path(str(configured))
        if base.exists() and base.name.startswith("pytest-tmp"):
            shutil.rmtree(base, ignore_errors=True)
    # Second pass for anything left from parallel/aborted runs.
    cleanup_stale_pytest_tmp(root)


@pytest.fixture(autouse=True)
def _reset_creo_page_cache():
    from creopdm.api.pages import clear_creo_page_cache

    clear_creo_page_cache()
    yield
    clear_creo_page_cache()


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    root = tmp_path / "appdata"
    monkeypatch.setenv("CREOPDM_DATA_DIR", str(root))
    return root


@pytest.fixture()
def identity():
    return StaticUserProvider("Alice", "ENG-PC-17")


@pytest.fixture()
def app(data_dir, identity):
    return create_app(build_context(ConfigManager(), users=identity))


@pytest.fixture()
def client(app):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def repo_parent(tmp_path):
    path = tmp_path / "repos"
    path.mkdir()
    return path


def git_available() -> bool:
    return GitService().is_available()


requires_git = pytest.mark.skipif(not git_available(), reason="Git is not available on PATH")


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Write a shareable run log at the repo root after every pytest."""
    log_path = Path(config.rootpath) / PYTEST_LAST_LOG
    stats = terminalreporter.stats
    passed = len(stats.get("passed", []))
    failed = stats.get("failed", [])
    errors = stats.get("error", [])
    skipped = len(stats.get("skipped", []))
    warns = stats.get("warnings", [])
    lines = [
        f"exitstatus={exitstatus}",
        f"passed={passed} failed={len(failed)} errors={len(errors)} skipped={skipped} warnings={len(warns)}",
    ]
    if warns:
        lines.append("")
        lines.append("WARNINGS")
        grouped: Counter[str] = Counter()
        for item in warns:
            message = str(getattr(item, "message", item)).splitlines()[0].strip()
            grouped[message[:240]] += 1
        for message, count in grouped.most_common():
            lines.append(f"{count}x {message}")
    for report in [*failed, *errors]:
        lines.append("")
        kind = "ERROR" if report.outcome == "error" else "FAILED"
        lines.append(f"{kind} {report.nodeid}")
        longrepr = getattr(report, "longrepr", None)
        if longrepr is not None:
            lines.append(str(longrepr))
    log_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    terminalreporter.write_line(f"Wrote {log_path}")
