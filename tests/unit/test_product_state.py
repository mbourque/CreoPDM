"""Product lifecycle state (project) + read-only access."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from creopdm.constants import ProductState
from creopdm.exceptions import ValidationAppError
from creopdm.product_state import (
    ensure_product_mutable,
    parse_product_state,
    product_allows_mutation,
    product_state_label,
)


def test_product_state_defaults_allow_mutation():
    product = SimpleNamespace(uuid="p1", state=ProductState.IN_WORK.value, read_only=False)
    assert product_allows_mutation(product) is True
    ensure_product_mutable(product)


@pytest.mark.parametrize(
    "state",
    [
        ProductState.ON_HOLD.value,
        ProductState.RELEASED.value,
        ProductState.CLOSED.value,
        ProductState.ARCHIVED.value,
    ],
)
def test_non_in_work_blocks_mutation(state):
    product = SimpleNamespace(uuid="p1", state=state, read_only=False)
    assert product_allows_mutation(product) is False
    with pytest.raises(ValidationAppError) as exc:
        ensure_product_mutable(product, action="check out files")
    assert "cannot check out files" in exc.value.message
    assert product_state_label(state) in exc.value.message


def test_read_only_blocks_even_when_in_work():
    product = SimpleNamespace(uuid="p1", state=ProductState.IN_WORK.value, read_only=True)
    assert product_allows_mutation(product) is False
    with pytest.raises(ValidationAppError) as exc:
        ensure_product_mutable(product)
    assert "read-only" in exc.value.message.lower()


def test_parse_product_state_rejects_unknown():
    with pytest.raises(ValidationAppError):
        parse_product_state("WIP")
    assert parse_product_state("on_hold") == ProductState.ON_HOLD.value
