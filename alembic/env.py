"""Alembic environment configuration.

This file is executed by Alembic when running migrations. It sets up the
SQLAlchemy ``MetaData`` object that Alembic uses to compare the current
database schema with the target schema defined in the models.

The configuration is intentionally minimal – it pulls the database URL from
the ``DATABASE_URL`` environment variable (the same variable used by the
application) and imports the ``Base`` from ``models``.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from sqlalchemy import create_engine

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
from models import Base

target_metadata = Base.metadata

# other values from the config, if any
# e.g. config.get_main_option("sqlalchemy.url")

# this is the database URL used by the application.
# It is expected to be set in the environment.
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is not set")

# create an engine for the migration context
engine = create_engine(DATABASE_URL, poolclass=pool.NullPool)

# this is the Alembic migration context
# it is used to run migrations against the database.

def run_migrations_offline():
    """Run migrations in 'offline' mode.

    This configures the context with just a URL and does not
    connect to the database.  It is useful for generating
    SQL scripts.
    """
    url = DATABASE_URL
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    """Run migrations in 'online' mode.

    This connects to the database and runs the migrations.
    """
    connectable = engine

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
