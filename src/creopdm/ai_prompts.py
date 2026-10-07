"""Reusable prompts for CreoPDM AI features (Ollama)."""

from __future__ import annotations

import json
from typing import Any

# System role: stable instructions the model should follow every compare.
# Tuned to match the change-notice style the user validated with ChatGPT.
SNAPSHOT_COMPARE_SYSTEM_PROMPT = """\
You compare two CreoPDM model snapshots (schema v1 JSON) for the same Creo part.
The user message always includes both: older JSON first, then newer JSON.

Write one short paragraph suitable as a change notice / check-in comment.
Plain language only — no tables, bullets, headings, markdown, emoji, or JSON.

Rules:
- Report only facts present in the snapshots (feature add/remove/rename; dimension
  value changes; tolerance upper/lower when those fields change; material/parameter
  changes).
- Prefer named dims (width, length, height, angle) over anonymous dN.
- Include units when known (mm, deg).
- Do not invent. No "± allowance," fits, design intent, or "likely driven by…"
  unless that text appears in the JSON.
- For limits, say the old and new limits plainly (e.g. "d31 from 15 mm (limits
  14–16) to 20 mm (limits 19–21)"). Do not restate them as a bilateral ± tolerance.
- Skip noise: empty MC_* values, tiny float dust, hashes, timestamps, UUIDs.
- Never say there is no previous state or only one snapshot — both are always
  provided. Do not restate the whole part; only what changed from older to newer.
"""


def build_snapshot_compare_user_prompt(
    *,
    older_snapshot: dict[str, Any],
    newer_snapshot: dict[str, Any],
    older_revision: str = "",
    newer_revision: str = "",
) -> str:
    """User message: older then newer JSON, matching the ChatGPT paste order."""
    older_label = (older_revision or "").strip() or "older"
    newer_label = (newer_revision or "").strip() or "newer"
    older_json = json.dumps(older_snapshot, ensure_ascii=False, indent=2, default=str)
    newer_json = json.dumps(newer_snapshot, ensure_ascii=False, indent=2, default=str)
    return (
        f"Older revision ({older_label}):\n{older_json}\n\n"
        f"Newer revision ({newer_label}):\n{newer_json}\n\n"
        f"Write one short paragraph change notice for what changed from "
        f"{older_label} to {newer_label}, following your rules."
    )
