"""Creación inicial de tablas troncales core_executions y core_audit_records.

Revision ID: 0001_initial_core
Revises:
Create Date: 2026-09-04 20:55:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_initial_core"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Tabla core_executions
    op.create_table(
        "core_executions",
        sa.Column("execution_id", sa.String(length=64), nullable=False),
        sa.Column("thread_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("response", sa.Text(), nullable=True),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("user_context", sa.JSON(), nullable=True),
        sa.Column("execution_time_ms", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("requires_approval", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("pending_approval_id", sa.String(length=128), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("execution_id", name="core_pk_core_executions"),
    )
    op.create_index(
        "core_ix_core_executions_thread_id",
        "core_executions",
        ["thread_id"],
        unique=False,
    )
    op.create_index(
        "core_ix_core_executions_status",
        "core_executions",
        ["status"],
        unique=False,
    )

    # 2. Tabla core_audit_records
    op.create_table(
        "core_audit_records",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("execution_id", sa.String(length=64), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("actor", sa.String(length=64), nullable=False, server_default="agent"),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["core_executions.execution_id"],
            name="core_fk_core_audit_records_execution_id_core_executions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="core_pk_core_audit_records"),
    )
    op.create_index(
        "core_ix_core_audit_records_execution_id",
        "core_audit_records",
        ["execution_id"],
        unique=False,
    )
    op.create_index(
        "core_ix_core_audit_records_event_type",
        "core_audit_records",
        ["event_type"],
        unique=False,
    )
    op.create_index(
        "core_ix_core_audit_records_timestamp",
        "core_audit_records",
        ["timestamp"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("core_ix_core_audit_records_timestamp", table_name="core_audit_records")
    op.drop_index("core_ix_core_audit_records_event_type", table_name="core_audit_records")
    op.drop_index("core_ix_core_audit_records_execution_id", table_name="core_audit_records")
    op.drop_table("core_audit_records")

    op.drop_index("core_ix_core_executions_status", table_name="core_executions")
    op.drop_index("core_ix_core_executions_thread_id", table_name="core_executions")
    op.drop_table("core_executions")
