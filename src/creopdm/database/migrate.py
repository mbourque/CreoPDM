"""Alembic migration runner used at application startup."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

from creopdm.logging_setup import get_logger

logger = get_logger("database")

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def alembic_config(database_url: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", database_url)
    cfg.set_main_option("prepend_sys_path", ".")
    return cfg


def run_migrations(database_url: str) -> None:
    logger.info("Running database migrations")
    command.upgrade(alembic_config(database_url), "head")
    logger.info("Database migrations complete")
