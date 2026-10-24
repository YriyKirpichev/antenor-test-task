import asyncio
from logging.config import fileConfig

from alembic import context
from geoalchemy2 import alembic_helpers
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import settings
from app.models import Base  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", str(settings.database_url))

target_metadata = Base.metadata

EXCLUDED_SCHEMAS = frozenset({"tiger", "tiger_data", "topology"})


def include_object(
    obj: object, name: str | None, type_: str, reflected: bool, compare_to: object
) -> bool:
    if getattr(obj, "schema", None) in EXCLUDED_SCHEMAS:
        return False
    if reflected:
        if type_ == "table" and name not in target_metadata.tables:
            return False
        table = getattr(obj, "table", None)
        if type_ == "index" and table is not None:
            if table.name not in target_metadata.tables:
                return False
    return alembic_helpers.include_object(obj, name, type_, reflected, compare_to)


def _configure(connection: Connection | None = None, url: str | None = None) -> None:
    context.configure(
        connection=connection,
        url=url,
        target_metadata=target_metadata,
        literal_binds=url is not None,
        compare_type=True,
        compare_server_default=True,
        include_schemas=False,
        include_object=include_object,
        render_item=alembic_helpers.render_item,
    )


def run_migrations_offline() -> None:
    _configure(url=config.get_main_option("sqlalchemy.url"))
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    _configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
