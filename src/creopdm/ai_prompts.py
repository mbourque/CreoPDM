"""Defaults and helpers for CreoPDM AI prompts (editable copy lives in AI settings)."""

from __future__ import annotations

import json
from typing import Any

# Seed text for Administration → AI → Snapshot compare prompt (persisted in settings).
# Compare uses the saved setting, not this constant, once the admin has saved.
DEFAULT_SNAPSHOT_COMPARE_PROMPT = """\
You compare two CreoPDM model snapshots (schema v1 JSON) for the same Creo part.
The user message includes older JSON first, then newer JSON.

Write one short paragraph suitable as a change notice / check-in comment. Plain language only — no tables, bullets, headings, or JSON.

Rules:
- Report only facts present in the snapshots (feature add/remove/rename; dimension value changes; tolerance upper/lower when those fields change; material/parameter changes).
- Diff the features arrays: name every feature type removed (older only) and added (newer only). If both a chamfer and a round were removed, say both.
- Prefer named dims (width, length, height, angle) over anonymous dN.
- Include units when known (mm, deg).
- Do not invent. No "± allowance," fits, design intent, or "likely driven by…" unless that text appears in the JSON.
- For limits, say the old and new limits plainly (e.g. "d31 from 15 mm (limits 14–16) to 20 mm (limits 19–21)"). Do not restate them as a bilateral ± tolerance.
- Skip noise: empty MC_* values, tiny float dust, hashes, timestamps, UUIDs.
"""


def resolve_snapshot_compare_prompt(saved: str | None) -> str:
    """Use the AI-settings prompt when set; otherwise the seed default."""
    text = str(saved or "").strip()
    return text or DEFAULT_SNAPSHOT_COMPARE_PROMPT.strip()


def build_snapshot_compare_user_prompt(
    *,
    older_snapshot: dict[str, Any],
    newer_snapshot: dict[str, Any],
    older_revision: str = "",
    newer_revision: str = "",
) -> str:
    """User message: older then newer JSON only (instructions come from AI settings)."""
    older_label = (older_revision or "").strip() or "older"
    newer_label = (newer_revision or "").strip() or "newer"
    older_json = json.dumps(older_snapshot, ensure_ascii=False, indent=2, default=str)
    newer_json = json.dumps(newer_snapshot, ensure_ascii=False, indent=2, default=str)
    return (
        f"Older revision ({older_label}):\n{older_json}\n\n"
        f"Newer revision ({newer_label}):\n{newer_json}\n\n"
        f"Summarize what changed from {older_label} to {newer_label}, "
        f"following your instructions."
    )
