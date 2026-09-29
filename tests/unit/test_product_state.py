"""Product lifecycle state (project) + read-only access."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from creopdm.constants import ProductState
from creopdm.exceptions import ValidationAppError
from creopdm.product_state import (
    ensure_product_deletable,
    ensure_product_mutable,
    parse_product_state,
    product_allows_delete,
    product_allows_mutation,
    product_is_archived,
    product_state_label,
)


def test_product_state_defaults_allow_mutation():
    product = SimpleNamespace(uuid="p1", state=ProductState.IN_WORK.value, read_only=False)
    assert product_allows_mutation(product) is True
    assert product_allows_delete(product) is True
    ensure_product_mutable(product)
    ensure_product_deletable(product)


@pytest.mark.parametrize(
    "state",
    [
        ProductState.ON_HOLD.value,
        ProductState.RELEASED.value,
        ProductState.CLOSED.value,
        ProductState.ARCHIVED.value,
    ],
)
def test_non_in_work_blocks_mutation_and_delete(state):
    product = SimpleNamespace(uuid="p1", state=state, read_only=False)
    assert product_allows_mutation(product) is False
    assert product_allows_delete(product) is False
    with pytest.raises(ValidationAppError) as exc:
        ensure_product_mutable(product, action="check out files")
    assert "cannot check out files" in exc.value.message
    assert product_state_label(state) in exc.value.message
    with pytest.raises(ValidationAppError):
        ensure_product_deletable(product)


def test_read_only_blocks_even_when_in_work():
    product = SimpleNamespace(uuid="p1", state=ProductState.IN_WORK.value, read_only=True)
    assert product_allows_mutation(product) is False
    assert product_allows_delete(product) is False
    with pytest.raises(ValidationAppError) as exc:
        ensure_product_mutable(product)
    assert "read-only" in exc.value.message.lower()
    with pytest.raises(ValidationAppError) as exc2:
        ensure_product_deletable(product, action="delete this product")
    assert "read-only" in exc2.value.message.lower()


def test_archived_helper():
    assert product_is_archived(SimpleNamespace(state="ARCHIVED", read_only=False)) is True
    assert product_is_archived(SimpleNamespace(state="IN_WORK", read_only=False)) is False


def test_parse_product_state_rejects_unknown():
    with pytest.raises(ValidationAppError):
        parse_product_state("WIP")
    assert parse_product_state("on_hold") == ProductState.ON_HOLD.value
