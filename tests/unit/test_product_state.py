"""Product lifecycle state (project) + read-only / Locked access."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from creopdm.constants import ProductState
from creopdm.exceptions import ValidationAppError
from creopdm.lifecycle_policy import default_lifecycle_policy, set_lifecycle_policy
from creopdm.product_state import (
    configured_product_state_labels,
    configured_product_states,
    ensure_product_content_accessible,
    ensure_product_deletable,
    ensure_product_mutable,
    parse_product_state,
    product_allows_content_access,
    product_allows_delete,
    product_allows_mutation,
    product_is_archived,
    product_state_label,
    product_ui_capabilities,
)


@pytest.fixture(autouse=True)
def _default_lifecycle_policy():
    set_lifecycle_policy(default_lifecycle_policy())
    yield
    set_lifecycle_policy(default_lifecycle_policy())


def test_product_state_order_matches_common_pdm_plus_locked():
    assert configured_product_states() == [
        "PRE_WORK",
        "IN_WORK",
        "IN_REVIEW",
        "APPROVED",
        "RELEASED",
        "UNDER_CHANGE",
        "OBSOLETE",
        "ARCHIVED",
        "LOCKED",
    ]
    labels = configured_product_state_labels()
    assert labels[ProductState.PRE_WORK.value] == "Pre-Work"
    assert labels[ProductState.IN_WORK.value] == "In Work"
    assert labels[ProductState.UNDER_CHANGE.value] == "Under Change"


def test_product_state_defaults_allow_mutation():
    product = SimpleNamespace(uuid="p1", state=ProductState.IN_WORK.value, read_only=False)
    assert product_allows_mutation(product) is True
    assert product_allows_content_access(product) is True
    assert product_allows_delete(product) is True
    ensure_product_mutable(product)
    ensure_product_content_accessible(product)
    ensure_product_deletable(product)


def test_pre_work_allows_mutation():
    product = SimpleNamespace(uuid="p1", state=ProductState.PRE_WORK.value, read_only=False)
    assert product_allows_mutation(product) is True
    assert product_allows_content_access(product) is True
    ensure_product_mutable(product, action="check out files")


def test_under_change_allows_mutation():
    product = SimpleNamespace(uuid="p1", state=ProductState.UNDER_CHANGE.value, read_only=False)
    assert product_allows_mutation(product) is True
    ensure_product_mutable(product, action="check out files")


@pytest.mark.parametrize(
    "state",
    [
        ProductState.IN_REVIEW.value,
        ProductState.APPROVED.value,
        ProductState.RELEASED.value,
        ProductState.OBSOLETE.value,
        ProductState.ARCHIVED.value,
        ProductState.LOCKED.value,
    ],
)
def test_non_mutable_states_block_mutation_but_allow_delete(state):
    product = SimpleNamespace(uuid="p1", state=state, read_only=False)
    assert product_allows_mutation(product) is False
    assert product_allows_delete(product) is True
    with pytest.raises(ValidationAppError) as exc:
        ensure_product_mutable(product, action="check out files")
    assert "cannot check out files" in exc.value.message
    assert product_state_label(state) in exc.value.message
    ensure_product_deletable(product)


def test_locked_blocks_content_access():
    product = SimpleNamespace(uuid="p1", state=ProductState.LOCKED.value, read_only=False)
    assert product_allows_content_access(product) is False
    with pytest.raises(ValidationAppError) as exc:
        ensure_product_content_accessible(product, action="download files from this product")
    assert "Locked" in exc.value.message
    assert "cannot download" in exc.value.message.lower()


@pytest.mark.parametrize(
    "state",
    [
        ProductState.IN_REVIEW.value,
        ProductState.APPROVED.value,
        ProductState.RELEASED.value,
        ProductState.OBSOLETE.value,
        ProductState.ARCHIVED.value,
        ProductState.IN_WORK.value,
    ],
)
def test_non_locked_states_allow_content_access(state):
    product = SimpleNamespace(uuid="p1", state=state, read_only=True)
    assert product_allows_content_access(product) is True
    ensure_product_content_accessible(product)


def test_read_only_blocks_mutation_but_allows_delete():
    product = SimpleNamespace(uuid="p1", state=ProductState.IN_WORK.value, read_only=True)
    assert product_allows_mutation(product) is False
    assert product_allows_delete(product) is True
    with pytest.raises(ValidationAppError) as exc:
        ensure_product_mutable(product)
    assert "read-only" in exc.value.message.lower()
    ensure_product_deletable(product, action="delete this product")


def test_archived_helper():
    assert product_is_archived(SimpleNamespace(state="ARCHIVED", read_only=False)) is True
    assert product_is_archived(SimpleNamespace(state="IN_WORK", read_only=False)) is False


def test_parse_product_state_and_legacy_aliases():
    with pytest.raises(ValidationAppError):
        parse_product_state("WIP")
    assert parse_product_state("in_review") == ProductState.IN_REVIEW.value
    assert parse_product_state("on_hold") == ProductState.IN_REVIEW.value
    assert parse_product_state("closed") == ProductState.OBSOLETE.value
    assert parse_product_state("under_change") == ProductState.UNDER_CHANGE.value


def _full_role_caps() -> dict:
    return {
        "can_add_objects": True,
        "can_checkout": True,
        "can_force_undo_checkout": True,
        "can_checkin": True,
        "can_view_objects": True,
        "can_export_product": True,
        "can_export_objects": True,
        "can_copy_to_vault": True,
        "can_remove_objects": True,
        "can_edit_product": True,
        "can_delete_product": True,
        "can_update_metadata": True,
        "can_revert_objects": True,
    }


def test_product_ui_in_work_shows_mutation_controls():
    product = SimpleNamespace(uuid="p1", state=ProductState.IN_WORK.value, read_only=False)
    ui = product_ui_capabilities(product, **_full_role_caps())
    assert ui.allows_mutation is True
    assert ui.allows_content is True
    assert ui.show_access_banner is False
    assert ui.show_add is True
    assert ui.show_checkout is True
    assert ui.show_undo_checkout is True
    assert ui.show_force_undo_checkout is True
    assert ui.show_checkin is True
    assert ui.show_open is True
    assert ui.show_download is True
    assert ui.show_export_product is True
    assert ui.show_export_objects is True
    assert ui.show_copy_to_vault is True
    assert ui.show_remove is True
    assert ui.show_remove_vault is True
    assert ui.show_remove_product is True
    assert ui.show_rename is True
    assert ui.show_delete_product is True
    assert ui.show_metadata_tools is True
    assert ui.show_revert is True


def test_product_ui_in_review_hides_checkout_actions_keeps_undo_and_open():
    """In Review / read-only: no Checkout selected/product or Check In; Undo + Open stay."""
    product = SimpleNamespace(uuid="p1", state=ProductState.IN_REVIEW.value, read_only=False)
    ui = product_ui_capabilities(product, **_full_role_caps())
    assert ui.allows_mutation is False
    assert ui.allows_content is True
    assert ui.show_access_banner is True
    assert ui.show_add is False
    assert ui.show_checkin is False
    assert ui.show_checkout is False
    assert ui.show_undo_checkout is True
    assert ui.show_force_undo_checkout is True
    assert ui.show_open is True
    assert ui.show_download is True
    assert ui.show_remove is True
    assert ui.show_remove_vault is False
    assert ui.show_remove_product is False
    assert ui.show_rename is False
    assert ui.show_delete_product is True
    assert ui.show_metadata_tools is False
    assert ui.show_revert is False


def test_product_ui_locked_hides_open_download_export():
    product = SimpleNamespace(uuid="p1", state=ProductState.LOCKED.value, read_only=False)
    ui = product_ui_capabilities(product, **_full_role_caps())
    assert ui.allows_mutation is False
    assert ui.allows_content is False
    assert ui.show_access_banner is True
    assert ui.show_open is False
    assert ui.show_download is False
    assert ui.show_export_product is False
    assert ui.show_export_objects is False
    assert ui.show_copy_to_vault is False
    assert ui.show_add is False
    assert ui.show_checkin is False
    assert ui.show_undo_checkout is True
    assert ui.show_delete_product is True


def test_product_ui_read_only_hides_checkout_and_checkin():
    product = SimpleNamespace(uuid="p1", state=ProductState.IN_WORK.value, read_only=True)
    ui = product_ui_capabilities(product, **_full_role_caps())
    assert ui.show_checkout is False
    assert ui.show_checkin is False
    assert ui.show_undo_checkout is True
    assert ui.show_add is False
    assert ui.show_open is True


def test_product_ui_force_undo_checkout_without_checkout_hides_checkout_actions():
    """Force Undo alone must not show Checkout selected/product/Undo (needs objects.checkout)."""
    product = SimpleNamespace(uuid="p1", state=ProductState.IN_WORK.value, read_only=False)
    ui = product_ui_capabilities(
        product,
        can_checkout=False,
        can_force_undo_checkout=True,
        can_view_objects=True,
    )
    assert ui.show_checkout is False
    assert ui.show_undo_checkout is False
    assert ui.show_force_undo_checkout is True
    assert ui.show_add is False


def test_product_ui_without_checkin_hides_checkin_menu():
    product = SimpleNamespace(uuid="p1", state=ProductState.IN_WORK.value, read_only=False)
    ui = product_ui_capabilities(
        product,
        can_checkout=True,
        can_checkin=False,
        can_view_objects=True,
    )
    assert ui.show_checkout is True
    assert ui.show_undo_checkout is True
    assert ui.show_checkin is False
    assert ui.show_add is False


def test_product_ui_respects_role_caps_when_mutable():
    product = SimpleNamespace(uuid="p1", state=ProductState.IN_WORK.value, read_only=False)
    ui = product_ui_capabilities(
        product,
        can_add_objects=False,
        can_checkout=True,
        can_checkin=False,
        can_view_objects=True,
        can_export_product=False,
        can_export_objects=True,
        can_copy_to_vault=False,
        can_remove_objects=True,
        can_edit_product=False,
        can_delete_product=False,
        can_update_metadata=False,
        can_revert_objects=False,
    )
    assert ui.show_add is False
    assert ui.show_checkout is True
    assert ui.show_undo_checkout is True
    assert ui.show_checkin is False
    assert ui.show_export_product is False
    assert ui.show_export_objects is True
    assert ui.show_copy_to_vault is False
    assert ui.show_remove_vault is True
    assert ui.show_rename is False
