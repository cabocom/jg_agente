"""Modelos ORM de SQLAlchemy para las entidades troncales de jg_agente.

Todas las tablas gestionadas por el Core cuentan con el prefijo obligatorio 'core_'.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class CoreExecution(Base):
    """Registro persistente de ejecuciones del agente."""

    __tablename__ = "core_executions"

    execution_id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        doc="Identificador único de la ejecución asignado por el invocador",
    )
    thread_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        index=True,
        doc="Identificador del hilo o sesión conversacional",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
        default="in_progress",
        doc="Estado actual o final de la ejecución (completed, failed, waiting_approval)",
    )
    prompt: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Instrucción de entrada normalizada",
    )
    response: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Respuesta generada por el agente",
    )
    parameters: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        doc="Parámetros suministrados al invocar",
    )
    data: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
        doc="Datos estructurados o artefactos producidos",
    )
    user_context: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
        doc="Contexto del usuario y permisos",
    )
    execution_time_ms: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        doc="Duración total en milisegundos",
    )
    requires_approval: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        doc="Indica si se interrumpió requiriendo intervención humana (HITL)",
    )
    pending_approval_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        doc="ID de la acción sujeta a aprobación",
    )
    error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Detalle del error en caso de fallo",
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        doc="Metadatos arbitrarios de contexto o telemetría",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        doc="Timestamp de creación",
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp de finalización",
    )

    # Relación 1 a N con trazas de auditoría
    audit_records: Mapped[list["CoreAuditRecord"]] = relationship(
        "CoreAuditRecord",
        back_populates="execution",
        cascade="all, delete-orphan",
    )


class CoreAuditRecord(Base):
    """Registro inmutable de auditoría para trazabilidad de eventos del agente."""

    __tablename__ = "core_audit_records"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
        doc="Identificador secuencial del registro de auditoría",
    )
    execution_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("core_executions.execution_id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        doc="Referencia a la ejecución que originó el evento (opcional)",
    )
    event_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        doc="Tipo de evento (ej. tool_called, approval_requested, workflow_started)",
    )
    actor: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="agent",
        doc="Actor o subsistema responsable del evento",
    )
    details: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        doc="Datos contextuales estructurados del evento",
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        default=lambda: datetime.now(UTC),
        doc="Timestamp UTC del evento",
    )

    # Relación inversa con la ejecución
    execution: Mapped[CoreExecution | None] = relationship(
        "CoreExecution",
        back_populates="audit_records",
    )
