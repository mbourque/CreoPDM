"""Configurable product lifecycle permission matrix."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from creopdm.lifecycle_policy import (
    default_lifecycle_policy,
    policy_from_dicts,
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
                "change_state": True,
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
