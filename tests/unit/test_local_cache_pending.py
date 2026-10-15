"""Navigator and Files share local_cache_pending.js for Modified detection."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "src/creopdm/static/js/local_cache_pending.js"


def _run_node(harness: str) -> list[str]:
    if not shutil.which("node"):
        pytest.skip("node not on PATH")
    result = subprocess.run(
        ["node", "-e", harness],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(ROOT),
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip() or "[]")


def test_local_cache_pending_indexes_numbered_saves_by_logical_path():
    """Vault shaft.prt must match cache shaft.prt.2 (Files algorithm)."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert "function logicalRelativePath(" in text
    assert "function indexLocalCacheTipsByLogical(" in text
    assert "function planNewerLocalCacheSaves(" in text
    assert "function resolvePendingCheckinUuids(" in text
    assert "bestByLogical" in text
    assert "bestByBasename" in text
    assert "newerSave" in text
    assert "agentCacheSafeRelativePath" in text
    # Index-hash mismatch marks pending without rehash; match + !newerSave skips.
    assert "indexHash !== item.vaultHash" in text
    assert "indexHash === item.vaultHash && !item.newerSave" in text


def test_local_cache_pending_node_resolve_numbered_save():
    """Node: vault tip matches highest .N cache path; index hash mismatch → uuid."""
    script_path = json.dumps(str(SCRIPT))
    harness = f"""
const fs = require("fs");
const vm = require("vm");
const code = fs.readFileSync({script_path}, "utf8");
const sandbox = {{ console }};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(code, sandbox);
const api = sandbox.CreoPdmLocalCachePending;
(async () => {{
  const ids = await api.resolvePendingCheckinUuids(
    [{{
      relative_path: "mech/600610010006.prt.2",
      filename: "600610010006.prt.2",
      content_hash: "aaa",
      size: 10,
    }}],
    [{{
      uuid: "u-mod",
      filename: "600610010006.prt",
      relative_path: "mech/600610010006.prt",
      can_checkin: true,
      current_version: {{ content_hash: "bbb", filename: "600610010006.prt" }},
    }}],
    async () => ({{}}),
    {{}}
  );
  process.stdout.write(JSON.stringify(ids));
}})().catch((err) => {{ console.error(err); process.exit(1); }});
"""
    assert _run_node(harness) == ["u-mod"]


def test_local_cache_pending_node_hash_when_newer_save_index_stale():
    """Node: same index hash as vault but higher .N still rehashes (Files rule)."""
    script_path = json.dumps(str(SCRIPT))
    harness = f"""
const fs = require("fs");
const vm = require("vm");
const code = fs.readFileSync({script_path}, "utf8");
const sandbox = {{ console }};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(code, sandbox);
const api = sandbox.CreoPdmLocalCachePending;
(async () => {{
  const ids = await api.resolvePendingCheckinUuids(
    [{{
      relative_path: "part.prt.3",
      filename: "part.prt.3",
      content_hash: "same",
      size: 10,
    }}],
    [{{
      uuid: "u-hash",
      filename: "part.prt",
      relative_path: "part.prt",
      can_checkin: true,
      current_version: {{ content_hash: "same", filename: "part.prt" }},
    }}],
    async (paths) => {{
      const out = {{}};
      paths.forEach((p) => {{ out[String(p).toLowerCase()] = "different"; }});
      return out;
    }},
    {{}}
  );
  process.stdout.write(JSON.stringify(ids));
}})().catch((err) => {{ console.error(err); process.exit(1); }});
"""
    assert _run_node(harness) == ["u-hash"]
