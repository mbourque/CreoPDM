"""Vault / workspace folder names under the CreoPDM vaults root."""

from __future__ import annotations

import re
import uuid

from creopdm.exceptions import PathValidationError, ValidationAppError

# Single path segment: letters, digits, dot, underscore, hyphen; no spaces.
_VAULT_FOLDER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,198}[A-Za-z0-9])?$")
_RESERVED = frozenset({".", "..", ".git", ".creopdm"})


def normalize_uuid_folder(value: str) -> str:
    """Return canonical UUID string (lowercase) or empty if not a UUID."""
    text = (value or "").strip()
    if not text:
        return ""
    try:
        return str(uuid.UUID(text))
    except (ValueError, AttributeError, TypeError):
        return ""


def validate_vault_folder(value: str) -> str:
    """Return a safe single-segment vault folder name.

    Raises ValidationAppError / PathValidationError on bad input.
    """
    raw = (value or "").strip()
    if not raw:
        raise ValidationAppError("A vault/workspace name is required.")
    if any(ch in raw for ch in ("/", "\\", ":", "\0")):
        raise PathValidationError(
            "Vault/workspace name cannot contain path separators.",
            details={"vault_folder": raw},
        )
    if " " in raw or any(ch.isspace() for ch in raw):
        raise ValidationAppError(
            "Vault/workspace name cannot contain spaces.",
            details={"vault_folder": raw},
        )
    if raw.lower() in _RESERVED or raw.startswith("."):
        raise ValidationAppError(
            "That vault/workspace name is reserved.",
            details={"vault_folder": raw},
        )
    as_uuid = normalize_uuid_folder(raw)
    if as_uuid:
        return as_uuid
    if len(raw) > 200:
        raise ValidationAppError(
            "Vault/workspace name is too long (max 200 characters).",
            details={"vault_folder": raw},
        )
    if not _VAULT_FOLDER_RE.fullmatch(raw):
        raise ValidationAppError(
            "Vault/workspace name may only use letters, numbers, dots, hyphens, and underscores.",
            details={"vault_folder": raw},
        )
    return raw
