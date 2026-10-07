"""Helpers for CreoPDM AI prompts (instructions live only in AI settings)."""

from __future__ import annotations

import copy
import json
from typing import Any

from creopdm.exceptions import ValidationAppError

# Drawing view Outline floats bloat Ollama prompts and can hang /api/chat for minutes.
_COMPARE_DROP_FEATURE_KEYS = frozenset({"outline"})
_COMPARE_DROP_CAPTURE_KEYS = frozenset({"captured_at"})
_COMPARE_DROP_TOP_KEYS = frozenset({"item"})


def resolve_snapshot_compare_prompt(saved: str | None) -> str:
    """Require the Administration → AI snapshot compare prompt (no code fallback)."""
    text = str(saved or "").strip()
    if not text:
        raise ValidationAppError(
            "No snapshot compare prompt is saved. Open Administration → AI, "
            "paste your prompt, and Save."
        )
    return text


def slim_snapshot_for_compare(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    """Copy a snapshot for Ollama — drop bulky / non-diff fields (view outlines, item meta)."""
    if not isinstance(snapshot, dict):
        return {}
    out = copy.deepcopy(snapshot)
    for key in _COMPARE_DROP_TOP_KEYS:
        out.pop(key, None)
    capture = out.get("capture")
    if isinstance(capture, dict):
        for key in _COMPARE_DROP_CAPTURE_KEYS:
            capture.pop(key, None)
    features = out.get("features")
    if isinstance(features, list):
        for feat in features:
            if not isinstance(feat, dict):
                continue
            for key in _COMPARE_DROP_FEATURE_KEYS:
                feat.pop(key, None)
    return out


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
    older_json = json.dumps(
        slim_snapshot_for_compare(older_snapshot),
        ensure_ascii=False,
        indent=2,
        default=str,
    )
    newer_json = json.dumps(
        slim_snapshot_for_compare(newer_snapshot),
        ensure_ascii=False,
        indent=2,
        default=str,
    )
    return (
        f"Older revision ({older_label}):\n{older_json}\n\n"
        f"Newer revision ({newer_label}):\n{newer_json}\n\n"
        f"Summarize what changed from {older_label} to {newer_label}, "
        f"following your instructions."
    )
