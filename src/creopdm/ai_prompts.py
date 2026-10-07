"""Reusable prompts for CreoPDM AI features (Ollama)."""

from __future__ import annotations

import json
from typing import Any

# System role: stable instructions the model should follow every compare.
SNAPSHOT_COMPARE_SYSTEM_PROMPT = """\
You compare two CreoPDM model snapshots captured from Creo (JSON).
The first snapshot is the OLDER revision; the second is the NEWER revision.

Write a clear summary for a CAD engineer in ordinary paragraphs (one or a few short
paragraphs). Do not use markdown tables, bullet lists, or numbered lists.

Cover meaningful differences in features, dimensions, parameters, materials, units,
and family table when those sections differ. Ignore noise such as identical empty
arrays or unchanged capture metadata.

For dimensions: state the nominal value and units. Only mention tolerance or limits
when the JSON includes tolerance_type and/or tolerance_limits (upper_limit /
lower_limit). Never invent a ± allowance or symmetric tolerance that is not present
in the JSON.

If almost nothing changed, say so briefly. Do not invent geometry, features, or
values that are not in the JSON.
"""


def build_snapshot_compare_user_prompt(
    *,
    older_snapshot: dict[str, Any],
    newer_snapshot: dict[str, Any],
    older_revision: str = "",
    newer_revision: str = "",
) -> str:
    """User message: labels + both snapshot JSON bodies."""
    older_label = (older_revision or "").strip() or "older"
    newer_label = (newer_revision or "").strip() or "newer"
    older_json = json.dumps(older_snapshot, ensure_ascii=False, indent=2, default=str)
    newer_json = json.dumps(newer_snapshot, ensure_ascii=False, indent=2, default=str)
    return (
        f"OLDER revision ({older_label}):\n```json\n{older_json}\n```\n\n"
        f"NEWER revision ({newer_label}):\n```json\n{newer_json}\n```\n\n"
        "Summarize what changed from older to newer, following your instructions."
    )
