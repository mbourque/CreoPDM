"""PostgreSQL readiness (URL + dialect assumptions; no live server required)."""

from __future__ import annotations

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex

from creopdm.database.session import create_db_engine
from creopdm.models.checkout import Checkout


def test_psycopg_driver_is_installable():
    """Settings use postgresql+psycopg:// — the psycopg package must be present."""
    import psycopg

    assert psycopg.__name__ == "psycopg"


def test_create_db_engine_postgres_skips_sqlite_pragmas(monkeypatch):
    """Non-SQLite URLs must not attach PRAGMA listeners or NullPool."""
    calls: list[dict] = []

    def fake_create_engine(url, **kwargs):
        calls.append({"url": url, "kwargs": kwargs})

        class _Engine:
            pass

        return _Engine()

    monkeypatch.setattr("creopdm.database.session.create_engine", fake_create_engine)

    url = "postgresql+psycopg://creopdm:secret@localhost:5432/CreoPDM"
    create_db_engine(url)
    assert len(calls) == 1
    assert calls[0]["url"] == url
    assert calls[0]["kwargs"].get("pool_pre_ping") is True
    assert "connect_args" not in calls[0]["kwargs"]
    assert "poolclass" not in calls[0]["kwargs"]


def test_active_checkout_partial_unique_index_compiles_for_postgres():
    """One ACTIVE checkout per object must remain enforced on PostgreSQL."""
    index = next(idx for idx in Checkout.__table__.indexes if idx.name == "uq_checkouts_object_active")
    assert index.unique is True
    ddl = str(CreateIndex(index).compile(dialect=postgresql.dialect()))
    assert "uq_checkouts_object_active" in ddl
    assert "WHERE" in ddl.upper()
    assert "ACTIVE" in ddl
