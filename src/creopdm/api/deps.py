"""FastAPI dependencies."""

from __future__ import annotations

from collections.abc import Generator

from fastapi import Request
from sqlalchemy.orm import Session

from creopdm.context import AppContext
from creopdm.exceptions import PermissionDeniedError, ValidationAppError
from creopdm.models.object import EngineeringObject
from creopdm.models.product import Product


def get_context(request: Request) -> AppContext:
    return request.app.state.ctx


def get_db(request: Request) -> Generator[Session, None, None]:
    ctx: AppContext = request.app.state.ctx
    session = ctx.session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def require_permission(request: Request, ctx: AppContext, key: str) -> None:
    """Enforce a permission when session auth is enabled."""
    if not ctx.auth_enabled:
        return
    perms = getattr(request.state, "permissions", None) or frozenset()
    if key in perms:
        return
    raise PermissionDeniedError("You do not have permission to perform this action.")


def require_product_access(request: Request, ctx: AppContext, product: Product) -> None:
    """Deny when the signed-in user is restricted away from this product."""
    if not ctx.auth_enabled:
        return
    user = getattr(request.state, "auth_user", None)
    if user is None:
        return
    if ctx.user_accounts.user_can_access_product(user, product):
        return
    raise PermissionDeniedError("You do not have access to this product.")


def load_accessible_objects(
    request: Request,
    ctx: AppContext,
    db: Session,
    object_ids: list[str] | None,
) -> list[EngineeringObject]:
    """Load objects by UUID and enforce product access for every id."""
    requested = [oid for oid in dict.fromkeys(object_ids or []) if oid]
    if not requested:
        return []
    objects = ctx.objects.get_objects(db, requested)
    found = {obj.uuid for obj in objects}
    missing = [oid for oid in requested if oid not in found]
    if missing:
        raise ValidationAppError(
            "One or more objects were not found.",
            details={"missing": missing[:20]},
        )
    for obj in objects:
        require_product_access(request, ctx, obj.product)
    return objects


def accessible_products(request: Request, ctx: AppContext, db: Session) -> list[Product]:
    """Products the current user may browse (all when auth off or All products)."""
    products = ctx.products.list_products(db)
    if not ctx.auth_enabled:
        return products
    user = getattr(request.state, "auth_user", None)
    if user is None:
        return products
    return ctx.user_accounts.filter_accessible_products(user, products)


def load_accessible_product(
    request: Request,
    ctx: AppContext,
    db: Session,
    product_id: str,
) -> Product:
    """Load a product and enforce membership when auth is on."""
    product = ctx.products.get_product(db, product_id)
    require_product_access(request, ctx, product)
    return product
