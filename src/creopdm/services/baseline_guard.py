"""Keep baselines intact: nothing a baseline pins may be destroyed, and a product delete cleans up.

Kept free of other services so object, product and utilities services can all import it.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from creopdm.exceptions import BaselineReferencedError
from creopdm.models.baseline import Baseline, BaselineDependency, BaselineMember
from creopdm.models.product_release import ProductRelease

_NAMES_SHOWN = 5


def _chunks(values: list[int], size: int = 400):
    for start in range(0, len(values), size):
        yield values[start : start + size]


def baseline_names_pinning(session: Session, object_ids: Iterable[int]) -> list[str]:
    """Names of the baselines that contain any of these objects (distinct, sorted)."""
    ids = [int(i) for i in object_ids if i is not None]
    names: set[str] = set()
    for chunk in _chunks(ids):
        rows = session.scalars(
            select(Baseline.name)
            .join(BaselineMember, BaselineMember.baseline_id == Baseline.id)
            .where(BaselineMember.object_id.in_(chunk))
            .distinct()
        )
        names.update(rows)
        # An edge also points at its child (even an unresolved one that is not a member).
        edge_rows = session.scalars(
            select(Baseline.name)
            .join(BaselineDependency, BaselineDependency.baseline_id == Baseline.id)
            .where(
                (BaselineDependency.child_object_id.in_(chunk))
                | (BaselineDependency.parent_object_id.in_(chunk))
            )
            .distinct()
        )
        names.update(edge_rows)
    return sorted(names, key=str.casefold)


def _referenced_error(names: list[str], action: str) -> BaselineReferencedError:
    shown = ", ".join(names[:_NAMES_SHOWN])
    more = f" and {len(names) - _NAMES_SHOWN} more" if len(names) > _NAMES_SHOWN else ""
    return BaselineReferencedError(
        f"Cannot {action}: the exact versions are kept by "
        f"{len(names)} baseline{'s' if len(names) != 1 else ''} ({shown}{more}).",
        details={"baselines": names},
    )


def ensure_objects_not_pinned(session: Session, object_ids: Iterable[int], *, action: str) -> None:
    """Refuse when any of these objects is a member of a baseline."""
    names = baseline_names_pinning(session, object_ids)
    if names:
        raise _referenced_error(names, action)


def ensure_product_has_no_baselines(session: Session, product_id: int, *, action: str) -> None:
    """Refuse a product-wide destructive action while the product has baselines."""
    names = sorted(
        session.scalars(select(Baseline.name).where(Baseline.product_id == product_id)),
        key=str.casefold,
    )
    if names:
        raise _referenced_error(names, action)


def count_product_baselines(session: Session, product_id: int) -> tuple[int, int]:
    """(baselines, releases) a product delete would erase: archived baselines count too."""
    from sqlalchemy import func

    baselines = session.scalar(
        select(func.count()).select_from(Baseline).where(Baseline.product_id == product_id)
    )
    releases = session.scalar(
        select(func.count()).select_from(ProductRelease).where(ProductRelease.product_id == product_id)
    )
    return int(baselines or 0), int(releases or 0)


def delete_product_baselines(session: Session, product_id: int) -> int:
    """Product delete: remove its releases, baselines and members, before objects and versions."""
    session.execute(delete(ProductRelease).where(ProductRelease.product_id == product_id))
    ids = list(session.scalars(select(Baseline.id).where(Baseline.product_id == product_id)))
    for chunk in _chunks(ids):
        session.execute(
            delete(BaselineDependency).where(BaselineDependency.baseline_id.in_(chunk))
        )
        session.execute(delete(BaselineMember).where(BaselineMember.baseline_id.in_(chunk)))
        session.execute(delete(Baseline).where(Baseline.id.in_(chunk)))
    return len(ids)
