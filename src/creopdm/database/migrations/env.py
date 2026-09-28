"""Alembic environment. Uses the application metadata, not ad-hoc SQL."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from creopdm.database.base import Base
from creopdm.models import (  # noqa: F401
    Activity,
    Checkout,
    Dependency,
    EngineeringObject,
    ObjectVersion,
    Parameter,
    Project,
    ProjectWatch,
    Remote,
)

config = context.config
if config.config_file_name is not None:
    try:
        fileConfig(config.config_file_name)
    except KeyError:
        pass

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = config.get_main_option("sqlalchemy.url")
    connect_args: dict = {}
    if url and (url.startswith("postgresql") or url.startswith("postgres")):
        # Avoid SQL_ASCII → bytes from psycopg3 (breaks SQLAlchemy version parse).
        connect_args["client_encoding"] = "utf8"
    connectable = create_engine(
        url,
        poolclass=pool.NullPool,
        future=True,
        connect_args=connect_args,
    )
    try:
        with connectable.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                render_as_batch=True,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
