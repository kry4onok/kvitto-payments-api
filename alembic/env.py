"""Alembic environment using DATABASE_URL from the application environment."""

import os

from sqlalchemy import create_engine, pool

import app.models  # noqa: F401 - registers mapped tables with Base.metadata
from alembic import context
from app.database import Base

target_metadata = Base.metadata


def get_database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("Set DATABASE_URL before running Alembic")
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=get_database_url(), target_metadata=target_metadata, literal_binds=True
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(get_database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
