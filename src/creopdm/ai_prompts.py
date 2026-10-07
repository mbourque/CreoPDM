"""Defaults and helpers for CreoPDM AI prompts (editable copy lives in AI settings)."""

from __future__ import annotations

import json
from typing import Any

# Seed text for Administration → AI → Snapshot compare prompt (persisted in settings).
# Compare uses the saved setting, not this constant, once the admin has saved.
DEFAULT_SNAPSHOT_COMPARE_PROMPT = """\
You compare two CreoPDM model snapshots (schema v1 JSON) for the same Creo part.
The user message always includes both: older JSON first, then newer JSON.

Write one short paragraph suitable as a change notice / check-in comment.
Plain language only — no tables, bullets, headings, markdown, emoji, or JSON.

Rules:
- Report only facts present in the snapshots (feature add/remove/rename; dimension
  value changes; tolerance upper/lower when those fields change; material/parameter
  changes).
- Compare the features arrays carefully: name every feature type present in older
  but missing in newer (removed), and every feature type present in newer but
  missing in older (added). Do not stop after the first removal — if both a
  chamfer and a round were removed, say both.
- Prefer named dims (width, length, height, angle) over anonymous dN.
- Include units when known (mm, deg).
- Do not invent. No "± allowance," fits, design intent, manufacturing accuracy,
  mating assembly, "please ensure drawings are updated," or "likely driven by…"
  unless that exact text appears in the JSON.
- For limits, say the old and new limits plainly (e.g. "d31 from 15 mm (limits
  14–16) to 20 mm (limits 19–21)"). Do not restate them as a bilateral ± tolerance.
- Skip noise: empty MC_* values, tiny float dust, hashes, timestamps, UUIDs.
- Never say there is no previous state or only one snapshot — both are always
  provided. Do not restate the whole part; only what changed from older to newer.

Bad (never write like this):
"This revision incorporates several refinements and geometric adjustments to improve
manufacturing accuracy and optimize fit within the mating assembly. Please ensure
drawings are updated while maintaining compatibility with existing material
specifications (PET)."

Good (write like this):
"Reduced width and length from 120 to 100 mm and removed the chamfer and round
features. Hole-location and pattern dimensions decreased from 52.5 to 42.5 mm.
Dimension d2 increased from 17.296 to 21.913 mm. Dimension d31 changed from 15 mm
with limits of 14–16 mm to 20 mm with limits of 19–21 mm."
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
