import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine  # Added for async support

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
from app.db.database import Base  # Import your Base class here
from app.modules.auth.models.auth_models import User  # Import your models here
target_metadata = Base.metadata  # Set target_metadata to your Base's metadata


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


def do_run_migrations(connection):
    """Helper function to run sync migrations inside the async context."""
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode using an async engine."""
    # Retrieve the database URL string from the alembic config
    ini_section = config.get_section(config.config_ini_section, {})
    db_url = ini_section.get("sqlalchemy.url")
    
    # Create the async engine wrapper
    connectable = create_async_engine(db_url, poolclass=pool.NullPool)

    async def run_async():
        async with connectable.connect() as connection:
            # run_sync bridges the gap to allow the synchronous context manager to execute
            await connection.run_sync(do_run_migrations)

    # Execute the async loop runner
    asyncio.run(run_async())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()