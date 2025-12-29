from logging.config import fileConfig
from sqlalchemy import engine_from_config
from sqlalchemy import pool
from alembic import context
import sys
import re
from pathlib import Path

# Add parent directory to path to import your modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Import your Base and models
from infrastructure.database import Base
from config import DB_URL

# Import all models so Alembic can detect them
from models import (  # noqa: E402, F401
    User,
    Group,
    GroupMember,
    Expense,
    ExpenseParticipant,
    Payment
)

# this is the Alembic Config object
config = context.config

SYNC_DB_URL = re.sub(
    r'^postgresql\+asyncpg://',
    'postgresql+psycopg2://',
    DB_URL
)

# Use DB_URL directly from environment configuration
# In Docker: use 'postgres' as hostname (service name from docker-compose)
# Locally: use 'localhost' as hostname
# The DB_URL should be configured correctly in .env for each environment
config.set_main_option('sqlalchemy.url', SYNC_DB_URL)

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Add your model's MetaData object here for 'autogenerate' support
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
