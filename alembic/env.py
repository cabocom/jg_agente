# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez <contacto@javiergalvez.com>
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

import asyncio
from logging.config import fileConfig
from typing import Any

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

import app.db.models  # noqa: F401 - Asegura registro de entidades en Base.metadata
from alembic import context
from app.core.config import settings
from app.db.base import Base

# Configuración de Alembic
config = context.config

# Configurar logging si existe archivo ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Asignar metadata del Core
target_metadata = Base.metadata


def get_database_url() -> str:
    """Obtiene la URL asíncrona de base de datos desde Settings o config."""
    custom_url = config.get_main_option("sqlalchemy.url")
    if isinstance(custom_url, str) and not custom_url.startswith("driver://"):
        return custom_url
    return str(settings.async_database_url)


def include_object(
    object: Any,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: Any,
) -> bool:
    """Filtro estricto para gestionar exclusivamente tablas y objetos del Core (prefijo core_)."""
    if type_ == "table":
        return name is not None and name.startswith("core_")
    return True


def run_migrations_offline() -> None:
    """Ejecuta migraciones en modo 'offline' sin levantar engine vivo."""
    url = get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Aplica las migraciones sobre una conexión síncrona/adaptada."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Crea un motor asíncrono y delega la ejecución de migraciones en un contexto sincrónico."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_database_url()

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Ejecuta migraciones en modo 'online'."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(asyncio.run, run_async_migrations()).result()
    else:
        asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
