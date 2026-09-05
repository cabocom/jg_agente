"""Tests unitarios para los modelos de base de datos SQLAlchemy de jg_plugin_devops."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from jg_plugin_devops.models.db import (
    DevopsBase,
    DevopsIncident,
    DevopsSnapshot,
)


def test_table_names_and_naming_conventions() -> None:
    """Verifica que las tablas y restricciones usen de forma estricta el prefijo devops_."""
    assert DevopsSnapshot.__tablename__ == "devops_snapshots"
    assert DevopsIncident.__tablename__ == "devops_incidents"

    table_names = set(DevopsBase.metadata.tables.keys())
    assert "devops_snapshots" in table_names
    assert "devops_incidents" in table_names

    # Verificar que NINGUNA tabla tenga un prefijo diferente a devops_
    for t_name in table_names:
        assert t_name.startswith("devops_"), f"Tabla sin prefijo devops_: {t_name}"

    # Verificar convención de claves y restricciones
    incidents_table = DevopsBase.metadata.tables["devops_incidents"]
    fk_names = [fk.name for fk in incidents_table.foreign_keys if isinstance(fk.name, str)]
    for fk_name in fk_names:
        assert fk_name.startswith("devops_fk_"), f"FK sin prefijo devops_fk_: {fk_name}"


@pytest.mark.asyncio
async def test_devops_db_crud_and_relationships() -> None:
    """Valida la creación de tablas, inserción y relaciones con motor SQLite en memoria."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with engine.begin() as conn:
        await conn.run_sync(DevopsBase.metadata.create_all)

    snap_id = str(uuid.uuid4())
    inc_id = str(uuid.uuid4())

    async with session_factory() as session:
        snapshot = DevopsSnapshot(
            id=snap_id,
            timestamp=datetime.now(UTC),
            host_data={"hostname": "srv-test", "os": "Linux"},
            docker_data={"is_available": True, "containers": []},
            kubernetes_data={"is_available": False},
            incidents_data=[{"title": "High Memory", "severity": "high"}],
            host_metrics={"cpu_pct": 45.0},
            summary="Test snapshot summary",
        )
        incident = DevopsIncident(
            id=inc_id,
            snapshot_id=snap_id,
            severity="high",
            title="High Memory",
            component="host",
            description="RAM usage exceeded 90%",
            details={"ram_used_pct": 92.5},
            resolved=False,
        )
        session.add(snapshot)
        session.add(incident)
        await session.commit()

    async with session_factory() as session:
        query = select(DevopsSnapshot).where(DevopsSnapshot.id == snap_id)
        result = await session.execute(query)
        fetched_snap = result.scalar_one()

        assert fetched_snap.id == snap_id
        assert fetched_snap.host_data is not None
        assert fetched_snap.host_data["hostname"] == "srv-test"
        assert fetched_snap.summary == "Test snapshot summary"

        # Verificar incidente relacionado
        query_inc = select(DevopsIncident).where(DevopsIncident.id == inc_id)
        res_inc = await session.execute(query_inc)
        fetched_inc = res_inc.scalar_one()

        assert fetched_inc.id == inc_id
        assert fetched_inc.snapshot_id == snap_id
        assert fetched_inc.severity == "high"
        assert fetched_inc.component == "host"
        assert fetched_inc.resolved is False

    await engine.dispose()
