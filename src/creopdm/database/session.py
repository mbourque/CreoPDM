"""Database engine and session factory."""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from creopdm.database.base import Base


def _register_mappers() -> None:
    """Import model modules so SQLAlchemy maps are registered.

    Imported lazily to avoid a package-level cycle:
    models → database → session → models.
    """
    from creopdm.models.activity import Activity  # noqa: F401
    from creopdm.models.checkout import Checkout  # noqa: F401
    from creopdm.models.dependency import Dependency  # noqa: F401
    from creopdm.models.object import EngineeringObject  # noqa: F401
    from creopdm.models.parameter import Parameter  # noqa: F401
    from creopdm.models.project import Project  # noqa: F401
    from creopdm.models.remote import Remote  # noqa: F401
    from creopdm.models.version import ObjectVersion  # noqa: F401


def _is_sqlite(database_url: str) -> bool:
    return database_url.startswith("sqlite:")


def create_db_engine(database_url: str) -> Engine:
    _register_mappers()
    if _is_sqlite(database_url):
        engine = create_engine(
            database_url,
            connect_args={"check_same_thread": False, "timeout": 30},
            poolclass=NullPool,
            future=True,
        )

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

        return engine
    return create_engine(database_url, pool_pre_ping=True, future=True)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def session_scope(factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


__all__ = ["Base", "create_db_engine", "create_session_factory", "session_scope"]
