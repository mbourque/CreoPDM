"""Configurable product lifecycle states + permission matrix (settings.json)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from creopdm.constants import (
    PRODUCT_STATE_DESCRIPTIONS,
    PRODUCT_STATE_LABELS,
    PRODUCT_STATE_LEGACY_ALIASES,
    ProductState,
)
from creopdm.exceptions import ValidationAppError

# Ops admins can toggle per state (Allowed / Blocked). Role caps still apply on top.
LIFECYCLE_OPS: tuple[tuple[str, str], ...] = (
    ("view", "Read / View"),
    ("download", "Download / Export / Open"),
    ("checkout", "Check Out / Undo Checkout"),
    ("checkin", "Check In / Add / Upload"),
    ("remove", "Delete / Remove (vault)"),
    ("edit_metadata", "Edit Metadata"),
    ("rename", "Rename product"),
    ("history", "View History / Audit"),
)

LIFECYCLE_OP_KEYS: tuple[str, ...] = tuple(key for key, _ in LIFECYCLE_OPS)

# Ops that count as engineering "mutation" for banners / coarse ensure_product_mutable.
_MUTATION_OPS: frozenset[str] = frozenset(
    {"checkout", "checkin", "remove", "edit_metadata", "rename"}
)

_BUILTIN_KEYS: frozenset[str] = frozenset(s.value for s in ProductState)

_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,31}$")


def _perms(**overrides: bool) -> dict[str, bool]:
    base = {key: False for key in LIFECYCLE_OP_KEYS}
    base.update(
        {
            "view": True,
            "download": True,
            "history": True,
        }
    )
    base.update(overrides)
    return base


def _editable(**extra: bool) -> dict[str, bool]:
    return _perms(
        checkout=True,
        checkin=True,
        remove=True,
        edit_metadata=True,
        rename=True,
        **extra,
    )


def _frozen(**extra: bool) -> dict[str, bool]:
    return _perms(**extra)


def default_lifecycle_state_dicts() -> list[dict[str, Any]]:
    """Built-in matrix (order = Administration dropdown default)."""
    rows: list[tuple[str, dict[str, bool]]] = [
        (ProductState.PRE_WORK.value, _editable()),
        (ProductState.IN_WORK.value, _editable()),
        (ProductState.IN_REVIEW.value, _frozen()),
        (ProductState.APPROVED.value, _frozen()),
        (ProductState.RELEASED.value, _frozen()),
        (ProductState.UNDER_CHANGE.value, _editable()),
        (ProductState.OBSOLETE.value, _frozen()),
        (ProductState.ARCHIVED.value, _frozen()),
        (ProductState.LOCKED.value, _frozen(download=False)),
    ]
    out: list[dict[str, Any]] = []
    for order, (key, perms) in enumerate(rows):
        out.append(
            {
                "key": key,
                "label": PRODUCT_STATE_LABELS.get(key, key.replace("_", " ").title()),
                "description": PRODUCT_STATE_DESCRIPTIONS.get(key, ""),
                "order": order,
                "builtin": True,
                "permissions": dict(perms),
            }
        )
    return out


@dataclass(frozen=True)
class LifecycleStateDef:
    key: str
    label: str
    description: str
    order: int
    builtin: bool
    permissions: dict[str, bool]

    def allows(self, op: str) -> bool:
        return bool(self.permissions.get(op, False))


@dataclass
class LifecyclePolicy:
    states: list[LifecycleStateDef]

    def __post_init__(self) -> None:
        self.states = sorted(self.states, key=lambda s: (s.order, s.key))
        self._by_key = {s.key: s for s in self.states}

    def get(self, key: str | None) -> LifecycleStateDef | None:
        raw = (key or ProductState.IN_WORK.value).strip().upper()
        raw = PRODUCT_STATE_LEGACY_ALIASES.get(raw, raw)
        return self._by_key.get(raw)

    def known_keys(self) -> set[str]:
        return set(self._by_key)

    def label(self, key: str | None) -> str:
        state = self.get(key)
        if state is not None:
            return state.label
        raw = (key or "").strip().upper() or ProductState.IN_WORK.value
        return PRODUCT_STATE_LABELS.get(raw, raw.replace("_", " ").title())

    def allows(self, key: str | None, op: str) -> bool:
        state = self.get(key)
        if state is None:
            # Unknown state: conservative — view/history only.
            return op in {"view", "history"}
        return state.allows(op)

    def allows_mutation(self, key: str | None) -> bool:
        return any(self.allows(key, op) for op in _MUTATION_OPS)

    def ordered(self) -> list[LifecycleStateDef]:
        return list(self.states)

    def labels_map(self) -> dict[str, str]:
        return {s.key: s.label for s in self.states}

    def descriptions_map(self) -> dict[str, str]:
        return {s.key: s.description for s in self.states}

    def to_settings_dicts(self) -> list[dict[str, Any]]:
        return [
            {
                "key": s.key,
                "label": s.label,
                "description": s.description,
                "order": s.order,
                "builtin": s.builtin,
                "permissions": {op: s.allows(op) for op in LIFECYCLE_OP_KEYS},
            }
            for s in self.ordered()
        ]


def policy_from_dicts(rows: Iterable[dict[str, Any]] | None) -> LifecyclePolicy:
    defaults = {d["key"]: d for d in default_lifecycle_state_dicts()}
    merged: dict[str, dict[str, Any]] = {k: dict(v) for k, v in defaults.items()}
    if rows:
        for raw in rows:
            if not isinstance(raw, dict):
                continue
            key = str(raw.get("key") or "").strip().upper()
            if not key or not _KEY_RE.match(key):
                continue
            key = PRODUCT_STATE_LEGACY_ALIASES.get(key, key)
            base = merged.get(key) or {
                "key": key,
                "label": key.replace("_", " ").title(),
                "description": "",
                "order": len(merged),
                "builtin": key in _BUILTIN_KEYS,
                "permissions": _frozen(),
            }
            label = str(raw.get("label") or base["label"]).strip() or base["label"]
            description = str(raw.get("description") if raw.get("description") is not None else base["description"])
            try:
                order = int(raw.get("order", base["order"]))
            except (TypeError, ValueError):
                order = int(base["order"])
            builtin = bool(base.get("builtin")) if key in _BUILTIN_KEYS else bool(raw.get("builtin", False))
            perms = dict(base.get("permissions") or _frozen())
            raw_perms = raw.get("permissions") if isinstance(raw.get("permissions"), dict) else {}
            for op in LIFECYCLE_OP_KEYS:
                if op in raw_perms:
                    perms[op] = bool(raw_perms[op])
            merged[key] = {
                "key": key,
                "label": label,
                "description": description,
                "order": order,
                "builtin": builtin or key in _BUILTIN_KEYS,
                "permissions": perms,
            }
    # Always keep every built-in key present.
    for key, default in defaults.items():
        if key not in merged:
            merged[key] = dict(default)
        else:
            merged[key]["builtin"] = True
    states = [
        LifecycleStateDef(
            key=row["key"],
            label=str(row["label"]),
            description=str(row.get("description") or ""),
            order=int(row.get("order") or 0),
            builtin=bool(row.get("builtin")),
            permissions={op: bool((row.get("permissions") or {}).get(op, False)) for op in LIFECYCLE_OP_KEYS},
        )
        for row in merged.values()
    ]
    return LifecyclePolicy(states=states)


def default_lifecycle_policy() -> LifecyclePolicy:
    return policy_from_dicts(default_lifecycle_state_dicts())


_active_policy: LifecyclePolicy = default_lifecycle_policy()


def get_lifecycle_policy() -> LifecyclePolicy:
    return _active_policy


def set_lifecycle_policy(policy: LifecyclePolicy | None) -> LifecyclePolicy:
    global _active_policy
    _active_policy = policy or default_lifecycle_policy()
    return _active_policy


def set_lifecycle_policy_from_settings(lifecycle: Any) -> LifecyclePolicy:
    rows = None
    if lifecycle is not None:
        states = getattr(lifecycle, "states", None)
        if states is not None:
            rows = []
            for item in states:
                if hasattr(item, "model_dump"):
                    rows.append(item.model_dump())
                elif isinstance(item, dict):
                    rows.append(item)
    return set_lifecycle_policy(policy_from_dicts(rows))


def slugify_lifecycle_key(name: str) -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "_", (name or "").strip().upper()).strip("_")
    if not text:
        raise ValidationAppError("Lifecycle state name is required.")
    if text[0].isdigit():
        text = f"S_{text}"
    if not _KEY_RE.match(text):
        raise ValidationAppError(
            "Lifecycle state key must be letters, numbers, and underscores (max 32).",
            details={"key": text},
        )
    return text


def normalize_lifecycle_key(raw: str | None) -> str:
    key = (raw or ProductState.IN_WORK.value).strip().upper()
    return PRODUCT_STATE_LEGACY_ALIASES.get(key, key)
