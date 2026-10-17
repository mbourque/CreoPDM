"""Revise eligibility: may this file get a new revision (A.3 RELEASED → B.1)?

One rule set for the UI flags and the server check, so the Files list, the Details page and
the API can never disagree. Creating the revision itself is a later step.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from creopdm.constants import INITIAL_ITERATION, LifecycleState
from creopdm.exceptions import (
    ReviseActiveCheckoutError,
    ReviseInvalidLifecycleError,
    ReviseNextRevisionExistsError,
    ReviseNotAllowedError,
    ReviseRevisionSchemeError,
    ReviseSourceNotFoundError,
)
from creopdm.models.checkout import Checkout
from creopdm.models.object import EngineeringObject
from creopdm.models.version import ObjectVersion
from creopdm.product_state import (
    product_allows_op,
    product_is_archived,
    product_state_label,
    product_state_value,
)


@dataclass(frozen=True)
class ReviseEligibility:
    allowed: bool
    code: str = ""
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)


def evaluate_revise(
    obj: EngineeringObject,
    checkout: Checkout | None,
    *,
    check_product: bool = True,
) -> ReviseEligibility:
    """Object-level rules, in the order a user would hit them.

    ``check_product`` is False for list flags, where the product matrix is applied separately
    (``product_ui.show_revise``); the API always checks it.
    """
    # Only touch obj.product when asked: list flags run per row and must not lazy-load it.
    product = obj.product if check_product else None
    if product is not None:
        if product_is_archived(product):
            return ReviseEligibility(
                False,
                ReviseNotAllowedError.code,
                f"{product.name} is archived and cannot create a new revision.",
                {"product": product.uuid, "state": product_state_value(product)},
            )
        if not product_allows_op(product, "revise"):
            state = product_state_label(product_state_value(product))
            return ReviseEligibility(
                False,
                ReviseNotAllowedError.code,
                f"Product is {state} and cannot create a new revision.",
                {"product": product.uuid, "state": product_state_value(product), "op": "revise"},
            )
    if checkout is not None:
        return ReviseEligibility(
            False,
            ReviseActiveCheckoutError.code,
            f"Cannot revise {obj.filename}: it is checked out by {checkout.user_name}. "
            "Resolve the checkout before creating a new revision.",
            {"checked_out_by": checkout.user_name},
        )
    if obj.lifecycle_state != LifecycleState.RELEASED.value:
        state = (obj.lifecycle_state or "").replace("_", " ").title()
        return ReviseEligibility(
            False,
            ReviseInvalidLifecycleError.code,
            f"{obj.filename} is {state} — only a Released file can be revised.",
            {"lifecycle_state": obj.lifecycle_state},
        )
    return ReviseEligibility(True)


@dataclass(frozen=True)
class RevisePreview:
    """Eligibility plus the new version the server would create (nothing is created)."""

    eligibility: ReviseEligibility
    source_version_id: str
    source_revision: str
    source_iteration: int
    new_revision: str = ""
    new_iteration: int = INITIAL_ITERATION
    new_lifecycle_state: str = LifecycleState.IN_WORK.value


def next_revision_for(db: Session, obj: EngineeringObject) -> str:
    """Next revision after the object's current one, refusing to reuse an existing revision.

    History stays linear (A → B → C): the next revision must not already exist on any
    version of this object. Raises a REVISE_* error the preview turns into a message.
    """
    from creopdm.utils.revision_scheme import get_next_revision

    current = obj.revision
    nxt = get_next_revision(current)
    used = set(
        db.scalars(select(ObjectVersion.revision).where(ObjectVersion.object_id == obj.id))
    )
    if nxt in used:
        raise ReviseNextRevisionExistsError(
            f"{obj.filename} already has a revision {nxt}.",
            details={"revision": nxt},
        )
    return nxt


def preview_revise(
    db: Session, obj: EngineeringObject, checkout: Checkout | None
) -> RevisePreview:
    """Server-calculated preview. The source is always the object's exact current version."""
    source = obj.current_version
    source_id = source.uuid if source is not None else ""
    base = {
        "source_version_id": source_id,
        "source_revision": obj.revision,
        "source_iteration": obj.iteration,
    }
    eligibility = evaluate_revise(obj, checkout)
    if not eligibility.allowed:
        return RevisePreview(eligibility=eligibility, **base)
    if source is None:
        error = ReviseSourceNotFoundError(f"{obj.filename} has no version to revise from.")
        return RevisePreview(
            eligibility=ReviseEligibility(False, error.code, error.message), **base
        )
    try:
        new_revision = next_revision_for(db, obj)
    except (ReviseNextRevisionExistsError, ReviseRevisionSchemeError) as exc:
        return RevisePreview(
            eligibility=ReviseEligibility(False, exc.code, exc.message, exc.details), **base
        )
    return RevisePreview(eligibility=eligibility, new_revision=new_revision, **base)


def object_can_revise(obj: EngineeringObject, checkout: Checkout | None) -> bool:
    """Flag for ObjectResponse.can_revise (permission and product matrix are separate)."""
    return evaluate_revise(obj, checkout, check_product=False).allowed


def ensure_can_revise(obj: EngineeringObject, checkout: Checkout | None) -> None:
    """Raise the matching REVISE_* error when Revise is not allowed (for the create step)."""
    result = evaluate_revise(obj, checkout)
    if result.allowed:
        return
    error = {
        ReviseActiveCheckoutError.code: ReviseActiveCheckoutError,
        ReviseInvalidLifecycleError.code: ReviseInvalidLifecycleError,
    }.get(result.code, ReviseNotAllowedError)
    raise error(result.message, result.details)
