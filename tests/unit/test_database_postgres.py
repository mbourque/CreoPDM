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
    assert calls[0]["kwargs"].get("connect_args") == {"client_encoding": "utf8"}
    assert "poolclass" not in calls[0]["kwargs"]


def test_active_checkout_partial_unique_index_compiles_for_postgres():
    """One ACTIVE checkout per object must remain enforced on PostgreSQL."""
    index = next(idx for idx in Checkout.__table__.indexes if idx.name == "uq_checkouts_object_active")
    assert index.unique is True
    ddl = str(CreateIndex(index).compile(dialect=postgresql.dialect()))
    assert "uq_checkouts_object_active" in ddl
    assert "WHERE" in ddl.upper()
    assert "ACTIVE" in ddl


def test_alembic_config_accepts_url_encoded_password():
    """ConfigParser must not reject %XX in postgresql passwords (e.g. %40 for @)."""
    from creopdm.database.migrate import alembic_config

    url = "postgresql+psycopg://creopdm:P%40ss@localhost:5432/CreoPDM"
    cfg = alembic_config(url)
    assert cfg.get_main_option("sqlalchemy.url") == url


def test_database_url_accepts_literal_at_in_password():
    from creopdm.config import database_url_for_connect, database_url_for_display

    typed = "postgresql+psycopg://creopdm:P@ss@localhost:5432/CreoPDM"
    encoded = "postgresql+psycopg://creopdm:P%40ss@localhost:5432/CreoPDM"
    assert database_url_for_connect(typed) == encoded
    assert database_url_for_connect(encoded) == encoded
    assert database_url_for_display(encoded) == typed
    assert database_url_for_display(typed) == typed


def test_config_manager_encodes_password_for_connect(tmp_path, monkeypatch):
    monkeypatch.delenv("CREOPDM_DATABASE_URL", raising=False)
    from creopdm.config import ConfigManager

    manager = ConfigManager(tmp_path / "appdata")
    settings = manager.load()
    settings.database.url = "postgresql+psycopg://creopdm:P@ss@localhost:5432/CreoPDM"
    manager.save(settings)
    loaded = ConfigManager(tmp_path / "appdata")
    assert loaded.settings.database.url == "postgresql+psycopg://creopdm:P@ss@localhost:5432/CreoPDM"
    assert loaded.database_url() == "postgresql+psycopg://creopdm:P%40ss@localhost:5432/CreoPDM"
