"""Modelos ORM SQLAlchemy para persistencia de datos del plugin DevOps.

Garantiza el uso estricto del prefijo 'devops_' en tablas, índices, claves primarias,
claves foráneas y restricciones, asegurando el aislamiento completo de las tablas del Core ('core_*').
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    MetaData,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Convención de nombres estricta con prefijo devops_
devops_naming_convention = {
    "ix": "devops_ix_%(column_0_label)s",
    "uq": "devops_uq_%(table_name)s_%(column_0_name)s",
    "ck": "devops_ck_%(table_name)s_%(constraint_name)s",
    "fk": "devops_fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "devops_pk_%(table_name)s",
}

devops_metadata = MetaData(naming_convention=devops_naming_convention)


class DevopsBase(DeclarativeBase):
    """Clase base declarativa para todas las entidades ORM del plugin DevOps."""

    metadata = devops_metadata


class DevopsSnapshot(DevopsBase):
    """Persistencia de capturas consolidadas de infraestructura."""

    __tablename__ = "devops_snapshots"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="Identificador UUID único de la captura",
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        index=True,
        doc="Marca temporal de cuando se tomó la fotografía de infraestructura",
    )
    host_data: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
        doc="Serialización JSON del HostSnapshot",
    )
    docker_data: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
        doc="Serialización JSON del DockerSnapshot",
    )
    kubernetes_data: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
        doc="Serialización JSON del KubernetesSnapshot",
    )
    incidents_data: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
        doc="Lista de anomalías e incidentes detectados en formato JSON",
    )
    host_metrics: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
        doc="Métricas resumidas de CPU/RAM/Disco",
    )
    summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Resumen ejecutivo o diagnóstico del estado observado",
    )
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata",
        JSON,
        nullable=True,
        doc="Metadatos libres asociados a la captura",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        doc="Marca temporal de registro en base de datos",
    )

    incidents: Mapped[list["DevopsIncident"]] = relationship(
        "DevopsIncident",
        back_populates="snapshot",
        cascade="all, delete-orphan",
    )


class DevopsIncident(DevopsBase):
    """Persistencia de incidentes y anomalías de infraestructura detectadas."""

    __tablename__ = "devops_incidents"

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="Identificador único del incidente",
    )
    snapshot_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("devops_snapshots.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="Clave foránea a la captura de infraestructura origen",
    )
    severity: Mapped[str] = mapped_column(
        String(32),
        default="medium",
        nullable=False,
        index=True,
        doc="Nivel de severidad (critical, high, medium, low, info)",
    )
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Título sintético del incidente",
    )
    component: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        index=True,
        doc="Componente o subsistema afectado (e.g. host, docker, postgres, k8s)",
    )
    description: Mapped[str] = mapped_column(
        Text,
        default="",
        nullable=False,
        doc="Descripción detallada de la anomalía",
    )
    details: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
        doc="Detalles técnicos y trazas de la anomalía",
    )
    resolved: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
        doc="Indica si la anomalía ha sido resuelta",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        doc="Marca temporal de creación",
    )

    snapshot: Mapped[DevopsSnapshot | None] = relationship(
        "DevopsSnapshot",
        back_populates="incidents",
    )
