"""A model saved in a newer Creo than the running session is refused up front, not tried and failed."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
JS = ROOT / "src" / "creopdm" / "static" / "js"


def _read(name: str) -> str:
    return (JS / name).read_text(encoding="utf-8")


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_release_rule_with_real_values():
    script = (
        "const vm=require('vm');const fs=require('fs');"
        "const ctx={window:{}};"
        f"vm.runInNewContext(fs.readFileSync({json.dumps(str(JS / 'creo_workspace.js'))},'utf8'),ctx);"
        "const r=ctx.window.__creopdmCreoRelease;"
        "const cases=[['13.4.1.0','13.4.1.0'],['13.4.1.0','13.3.0.0'],['14.0.0.0','13.4.1.0'],"
        "['12.0.0.0','13.4.1.0'],['13.4.2.0','13.4.1.0'],['13.4.1.0','13.4.0.0'],['','13.4.1.0'],"
        "['13.4.1.0',''],['Creo 13.4.1.0','13.3.0.0'],['13.4','13.4.1.0']];"
        "console.log(JSON.stringify(cases.map(c=>r.newerThanSession(c[0],c[1]))));"
    )
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout
    assert json.loads(out) == [
        False,  # same release
        True,   # file 13.4, session 13.3: later minor
        True,   # file 14, session 13: later major
        False,  # file older than the session
        False,  # only the last numbers differ: allowed
        False,  # 13.4.1.0 in a 13.4.0.0 session: same major.minor, allowed
        False,  # no release stored for the file: never block
        False,  # session release unknown: never block
        True,   # a prefix like "Creo " is tolerated
        False,  # short form 13.4 equals 13.4.x
    ]


def test_every_way_into_creo_checks_the_release_first():
    shared = _read("creo_workspace.js")
    # the session's release comes from the Toolkit /health reply
    assert 'healthBody?.toolkit?.creo?.release' in shared and "_creoSessionRelease = reported" in shared
    msg = shared.split("async function newerReleaseMessage", 1)[1].split("async function ensureToolkitAgentHealthy", 1)[0]
    assert "was saved in Creo ${saved}, but this Creo session is ${session}" in msg
    assert "A model saved in a newer Creo cannot be opened in an older one." in msg
    # Open in Creo: before anything is downloaded
    op = _read("open.js")
    open_work = op.split("async function openPdmObjectWork", 1)[1]
    assert open_work.index("newerReleaseMessage(prepared.filename, prepared.creo_release)") < open_work.index(
        "materializeViaAgent(prepared)"
    )
    # metadata from Add / Check in / Open (push) and from Collect all / Rebuild (one target)
    push = shared.split("async function pushCreoMetadataForItems", 1)[1]
    assert push.index("await newerReleaseMessage(target.filename, target.creoRelease)") < push.index(
        "gatherCreoMetadataForFilename("
    )
    assert "target.newerRelease = true;" in push
    meta = _read("metadata.js")
    one = meta.split("async function pushOneCreoMetadataTarget", 1)[1]
    assert one.index("await newerReleaseMessage(target.filename, target.creoRelease)") < one.index(
        "prepareLocalPathForMetadata("
    )
    assert 'reason: "newer_release"' in one
    # a file the session can never read is not retried, and keeps the old metadata on Rebuild
    assert "again[i].newerRelease" in meta
    # opening a baseline's model: before the baseline is downloaded
    baseline_open = shared.split("async function openBaselineVersion", 1)[1]
    assert baseline_open.index("newerReleaseMessage(member.filename, member.creo_release)") < baseline_open.index(
        "probeCreoAgent()"
    )


def test_the_notice_for_files_from_a_newer_creo_gives_the_reason_without_filler():
    shared = _read("creo_workspace.js")
    body = shared.split("function noteCollectFailures", 1)[1].split("async function pushCreoMetadataForItems", 1)[0]
    assert "failed.every((target) => target.newerRelease)" in body
    assert "Metadata was not collected for ${shown}${more}: ${detail}" in body


def test_the_release_reaches_the_pages_that_need_it():
    app = _read("app.js")
    assert "creo_release: item.creo_release || \"\"," in app  # Add / Check in results
    assert "newerReleaseMessage," in app
    assert "creoRelease: String(row.creo_release || row.current_version?.creo_release" in _read("metadata.js")
    schema = (ROOT / "src" / "creopdm" / "schemas" / "common.py").read_text(encoding="utf-8")
    assert "creo_release: str | None = None" in schema.split("class BaselineMemberResponse", 1)[1][:900]
