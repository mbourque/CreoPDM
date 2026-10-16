"""Configurable product lifecycle permission matrix."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from creopdm.lifecycle_policy import (
    LIFECYCLE_OPS,
    LIFECYCLE_OP_KEYS,
    default_lifecycle_policy,
    describe_lifecycle_change,
    policy_from_dicts,
    promote_confirm_payload,
    set_lifecycle_policy,
    slugify_lifecycle_key,
)
from creopdm.product_state import (
    ensure_product_allows,
    parse_product_state,
    product_allows_content_access,
    product_allows_mutation,
    product_allows_op,
)
from creopdm.exceptions import ValidationAppError


@pytest.fixture(autouse=True)
def _default_policy():
    set_lifecycle_policy(default_lifecycle_policy())
    yield
    set_lifecycle_policy(default_lifecycle_policy())


def test_default_order_and_builtins():
    policy = default_lifecycle_policy()
    keys = [s.key for s in policy.ordered()]
    assert keys[0] == "PRE_WORK"
    assert keys[1] == "IN_WORK"
    assert "LOCKED" in keys
    assert policy.label("IN_WORK") == "In Work"
    assert policy.allows("IN_WORK", "checkout") is True
    assert policy.allows("IN_REVIEW", "checkout") is False
    assert policy.allows("LOCKED", "download") is False
    assert policy.allows("OBSOLETE", "download") is True


def test_custom_state_roundtrip_and_parse():
    rows = default_lifecycle_policy().to_settings_dicts()
    rows.append(
        {
            "key": "PROTO_A",
            "label": "Proto A",
            "description": "Custom",
            "order": 99,
            "builtin": False,
            "permissions": {
                "view": True,
                "download": True,
                "checkout": True,
                "checkin": True,
                "remove": False,
                "edit_metadata": False,
                "rename": False,
                "history": True,
            },
        }
    )
    set_lifecycle_policy(policy_from_dicts(rows))
    assert parse_product_state("proto_a") == "PROTO_A"
    product = SimpleNamespace(uuid="p1", state="PROTO_A")
    assert product_allows_op(product, "checkout") is True
    assert product_allows_mutation(product) is True


def test_matrix_can_block_in_work_checkout():
    rows = default_lifecycle_policy().to_settings_dicts()
    for row in rows:
        if row["key"] == "IN_WORK":
            row["permissions"]["checkout"] = False
    set_lifecycle_policy(policy_from_dicts(rows))
    product = SimpleNamespace(uuid="p1", state="IN_WORK")
    assert product_allows_op(product, "checkout") is False
    assert product_allows_op(product, "checkin") is True
    with pytest.raises(ValidationAppError):
        ensure_product_allows(product, "checkout")


def test_locked_blocks_download():
    product = SimpleNamespace(uuid="p1", state="LOCKED")
    assert product_allows_content_access(product) is False


def test_slugify_lifecycle_key():
    assert slugify_lifecycle_key("Proto A") == "PROTO_A"
    with pytest.raises(ValidationAppError):
        slugify_lifecycle_key("   ")


def test_matrix_has_no_change_state_op():
    """Leaving Locked must not depend on a Change Lifecycle State checkbox."""
    assert "change_state" not in LIFECYCLE_OP_KEYS
    for row in default_lifecycle_policy().to_settings_dicts():
        assert "change_state" not in row["permissions"]
    # Stale settings keys are dropped on merge.
    rows = default_lifecycle_policy().to_settings_dicts()
    for row in rows:
        if row["key"] == "LOCKED":
            row["permissions"]["change_state"] = False
    policy = policy_from_dicts(rows)
    locked = policy.get("LOCKED")
    assert locked is not None
    assert "change_state" not in locked.permissions


def test_promote_confirm_uses_lifecycle_matrix_labels():
    """Confirm copy follows the matrix columns, not a second hardcoded state story."""
    policy = default_lifecycle_policy()
    html = describe_lifecycle_change(policy, "IN_WORK", "IN_REVIEW")
    assert "Submitted for engineering review." in html
    for _key, label in LIFECYCLE_OPS:
        assert label in html
    assert "Check Out / Undo Checkout — no longer allowed" in html
    assert "Check In / Add / Upload — no longer allowed" in html
    assert "Read / View — no longer allowed" not in html
    locked = describe_lifecycle_change(policy, "IN_WORK", "LOCKED")
    assert "Download / Export / Open — no longer allowed" in locked
    assert "List files only" in locked
    same = describe_lifecycle_change(policy, "IN_REVIEW", "APPROVED")
    assert "the permission matrix is unchanged" in same
    rows = policy.to_settings_dicts()
    for row in rows:
        if row["key"] == "IN_REVIEW":
            row["label"] = "Peer Review"
            row["permissions"]["download"] = False
    custom = policy_from_dicts(rows)
    renamed = describe_lifecycle_change(custom, "IN_WORK", "IN_REVIEW")
    assert "Compared with In Work" in renamed
    assert "Download / Export / Open — no longer allowed" in renamed
    payload = promote_confirm_payload(custom)
    assert payload["labels"]["IN_REVIEW"] == "Peer Review"
    assert payload["effects"]["IN_WORK|IN_REVIEW"] == renamed
    assert payload["effects"]["IN_WORK|LOCKED"] == describe_lifecycle_change(custom, "IN_WORK", "LOCKED")
