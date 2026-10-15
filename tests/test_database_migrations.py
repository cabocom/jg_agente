# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez <contacto@javiergalvez.com>
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Tests unitarios y de integración para la base de datos async, modelos y migraciones Alembic."""

from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from alembic import command
from app.db import (
    Base,
    CoreAuditRecord,
    CoreExecution,
    core_metadata,
)


@pytest.fixture
def temp_db_path(tmp_path: Path) -> Path:
    """Provee la ruta a una base de datos temporal SQLite para pruebas."""
    return tmp_path / "test_core_migrations.db"


@pytest.fixture
def alembic_cfg(temp_db_path: Path) -> Config:
    """Configura una instancia de Alembic Config apuntando a la base temporal."""
    ini_path = Path(__file__).parent.parent / "alembic.ini"
    cfg = Config(str(ini_path))
    db_url = f"sqlite+aiosqlite:///{temp_db_path}"
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


class TestDatabaseConventions:
    """Pruebas de cumplimiento de la convención de nombres core_."""

    def test_metadata_naming_conventions_prefix(self) -> None:
        """Verifica que todas las restricciones e índices usen prefijo core_."""
        assert core_metadata.naming_convention["ix"] == "core_ix_%(column_0_label)s"
        assert core_metadata.naming_convention["uq"] == "core_uq_%(table_name)s_%(column_0_name)s"
        assert core_metadata.naming_convention["ck"] == "core_ck_%(table_name)s_%(constraint_name)s"
        assert core_metadata.naming_convention["fk"] == (
            "core_fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"
        )
        assert core_metadata.naming_convention["pk"] == "core_pk_%(table_name)s"

    def test_orm_models_table_names(self) -> None:
        """Verifica que las tablas declaradas comiencen estrictamente por core_."""
        assert CoreExecution.__tablename__ == "core_executions"
        assert CoreAuditRecord.__tablename__ == "core_audit_records"

        for table_name in Base.metadata.tables:
            assert table_name.startswith("core_")


class TestAlembicMigrations:
    """Pruebas de aplicación y reversión de migraciones Alembic."""

    def test_alembic_upgrade_and_downgrade(self, alembic_cfg: Config, temp_db_path: Path) -> None:
        """Verifica que alembic upgrade head y downgrade base se ejecuten sin errores."""
        # 1. Aplicar migración hacia head
        command.upgrade(alembic_cfg, "head")
        assert temp_db_path.exists()

        # 2. Revertir migración hacia base
        command.downgrade(alembic_cfg, "base")

        # 3. Volver a aplicar hacia head
        command.upgrade(alembic_cfg, "head")


@pytest.mark.asyncio
async def test_async_database_crud(alembic_cfg: Config, temp_db_path: Path) -> None:
    """Verifica operaciones CRUD asíncronas sobre las tablas core_ creadas por Alembic."""
    command.upgrade(alembic_cfg, "head")

    db_url = f"sqlite+aiosqlite:///{temp_db_path}"
    engine = create_async_engine(db_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        # Inserción de ejecución
        execution = CoreExecution(
            execution_id="exec-db-001",
            thread_id="th-db-001",
            status="completed",
            prompt="Diagnosticar base de datos",
            response="Diagnóstico completado sin anomalías",
            parameters={"level": "full"},
            data={"checked": True},
            user_context={"user_id": "admin"},
            execution_time_ms=120.5,
            requires_approval=False,
            metadata_={"environment": "test"},
        )
        session.add(execution)

        # Inserción de traza de auditoría vinculada
        audit_record = CoreAuditRecord(
            execution_id="exec-db-001",
            event_type="execution_created",
            actor="test_suite",
            details={"action": "bootstrap_test"},
        )
        session.add(audit_record)
        await session.commit()

    # Consulta y verificación
    async with session_factory() as session:
        stmt = select(CoreExecution).where(CoreExecution.execution_id == "exec-db-001")
        result = await session.execute(stmt)
        persisted = result.scalar_one_or_none()

        assert persisted is not None
        assert persisted.thread_id == "th-db-001"
        assert persisted.status == "completed"
        assert persisted.execution_time_ms == 120.5
        assert persisted.parameters == {"level": "full"}

        # Verificar auditoría
        audit_stmt = select(CoreAuditRecord).where(CoreAuditRecord.execution_id == "exec-db-001")
        audit_res = await session.execute(audit_stmt)
        audits = audit_res.scalars().all()
        assert len(audits) == 1
        assert audits[0].event_type == "execution_created"
        assert audits[0].actor == "test_suite"

    await engine.dispose()
