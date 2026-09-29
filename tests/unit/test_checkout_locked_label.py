"""Checkout column labels respect product lock (not misleading Available)."""

from __future__ import annotations

from types import SimpleNamespace

from creopdm.constants import LifecycleState, ProductState
from creopdm.services.checkout_service import CheckoutService


class _Users:
    def get_current_user(self):
        return SimpleNamespace(user_name="alice", machine_name="pc1")


def _svc() -> CheckoutService:
    return CheckoutService(
        objects=SimpleNamespace(),
        workspaces=SimpleNamespace(),
        locks=SimpleNamespace(),
        activities=SimpleNamespace(),
        users=_Users(),
    )


def test_describe_available_when_product_mutable():
    product = SimpleNamespace(uuid="p1", state=ProductState.IN_WORK.value, read_only=False)
    obj = SimpleNamespace(
        product=product,
        lifecycle_state=LifecycleState.IN_WORK.value,
    )
    view = _svc().describe(obj, None)
    assert view.label == "Available"
    assert view.can_checkout is True


def test_describe_read_only_not_available():
    product = SimpleNamespace(uuid="p1", state=ProductState.IN_WORK.value, read_only=True)
    obj = SimpleNamespace(
        product=product,
        lifecycle_state=LifecycleState.IN_WORK.value,
    )
    view = _svc().describe(obj, None)
    assert view.label == "Read only"
    assert view.can_checkout is False


def test_describe_on_hold_not_available():
    product = SimpleNamespace(uuid="p1", state=ProductState.ON_HOLD.value, read_only=False)
    obj = SimpleNamespace(
        product=product,
        lifecycle_state=LifecycleState.IN_WORK.value,
    )
    view = _svc().describe(obj, None)
    assert view.label == "On hold"
    assert view.can_checkout is False
