# Contexto de Proyecto: jg_agente

> **Fecha de Actualización:** 4 de septiembre de 2026  
> **Estado Global del Proyecto:** Fase 01 y Fase 02 completadas (100%), Fase 03 (Persistencia y Checkpointing) iniciada con `ISSUE-F03-T01` completado.  
> **Próxima Tarea Inmediata:** `ISSUE-F03-T02` (Configuración de PostgresSaver para checkpoints de LangGraph).  

---

## 1. Resumen Ejecutivo de la Tarea Completada

Se ha implementado el paquete `app/db/` y la infraestructura de migraciones con Alembic:
- Motor asíncrono `create_async_engine` y factoría de sesiones `async_sessionmaker`.
- Modelos ORM `CoreExecution` (`core_executions`) y `CoreAuditRecord` (`core_audit_records`).
- Convención de nombres en `core_metadata` garantizando que todo objeto de BD posea el prefijo `core_`.
- Migración `0001_initial_core` con soporte bidireccional (`upgrade` y `downgrade`).
- Filtro `include_object` en Alembic aislando estrictamente las tablas del Core de las tablas futuras de plugins.

---

## 2. Estado Actual del Repositorio

```text
jg_agente/
├── .gitlab-ci.yml            # Pipeline CI/CD (lint, test, build a registry.cabocom.net con tag de rama)
├── Dockerfile                # Multi-stage build con alembic y app copiados al runner
├── docker-compose.yml        # Orquestación con PostgreSQL (red jg_agente_net)
├── .env.example              # Plantilla de variables de entorno
├── pyproject.toml            # Dependencias actualizadas con alembic
├── alembic.ini               # Configuración centralizada de Alembic
├── alembic/
│   ├── env.py                # Configuración de migración async con filtro core_
│   └── versions/
│       └── 0001_initial_core_tables.py # Migración inicial
├── app/
│   ├── __init__.py           # Versión 0.1.0
│   ├── main.py               # Servidor FastAPI con /health y ping a PostgreSQL
│   ├── core/
│   │   ├── __init__.py
│   │   └── config.py         # Settings centralizados con async_database_url y sync_database_url
│   ├── db/
│   │   ├── __init__.py       # Exportación pública del módulo de BD
│   │   ├── base.py           # Base declarativa y core_naming_convention
│   │   ├── models.py         # CoreExecution y CoreAuditRecord
│   │   └── session.py        # async_engine, async_session_factory, get_async_session
│   └── models/
│       ├── __init__.py
│       ├── io.py             # AgentInput, AgentOutput, UserContext, ExecutionStatus
│       ├── state.py          # AgentState, append_reducer, IntentModel, ExecutionPlan
│       └── tools.py          # AgentTool, ToolResult, RiskLevel, ToolType
├── tests/
│   ├── __init__.py
│   ├── test_bootstrap.py
│   ├── test_health_endpoint.py
│   ├── test_io_models.py
│   ├── test_tool_models.py
│   ├── test_agent_state.py
│   └── test_database_migrations.py # Pruebas de migraciones y CRUD asíncrono
├── scripts/
│   └── check.sh              # Script unificado de validación (Ruff + MyPy + Pytest)
└── docs/
    └── issues/
        ├── ISSUE-F01-*.md
        ├── ISSUE-F02-*.md
        ├── ISSUE-F03-T01-analysis.md
        ├── ISSUE-F03-T01-walkthrough.md
        └── ISSUE-F03-T01-PROJECT_CONTEXT.md
```

---

## 3. Estado de la Fase 03: Persistencia y Checkpointing

- [x] **`ISSUE-F03-T01`**: Configuración de base de datos PostgreSQL y migraciones con Alembic.
- [ ] **`ISSUE-F03-T02`**: Configuración de PostgresSaver para checkpoints de LangGraph.
- [ ] **`ISSUE-F03-T03`**: Repositorios de persistencia Core (ExecutionRepository, AuditRepository).
