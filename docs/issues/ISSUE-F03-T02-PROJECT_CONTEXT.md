# Contexto de Proyecto: jg_agente

> **Fecha de Actualización:** 4 de septiembre de 2026  
> **Estado Global del Proyecto:** Fase 01 y Fase 02 completadas (100%), Fase 03 en progreso con `ISSUE-F03-T01` e `ISSUE-F03-T02` completados.  
> **Próxima Tarea Inmediata:** `ISSUE-F03-T03` (Repositorios de persistencia Core: ExecutionRepository y AuditRepository).  

---

## 1. Resumen Ejecutivo de la Tarea Completada

Se ha implementado el módulo de persistencia de checkpoints para LangGraph en PostgreSQL:
- Módulo `app/core/checkpointer.py` con integración de `PostgresSaver` y `MemorySaver`.
- Pool de conexiones transaccionales mediante `psycopg_pool.ConnectionPool` (`dict_row`, `open=True`).
- Creación de vistas SQL actualizables con prefijo `core_` (`core_checkpoints`, `core_checkpoint_blobs`, `core_checkpoint_writes`) garantizando que ningún componente o auditoría consulte tablas sin prefijo.
- Serialización segura `JsonPlusSerializer` incorporando explícitamente todas las clases Pydantic del Core.
- Tests de integración en `tests/test_checkpointer.py` demostrando el pausado de LangGraph por interrupción HITL y la posterior reanudación fluida desde el checkpoint almacenado en PostgreSQL.

---

## 2. Estado Actual del Repositorio

```text
jg_agente/
├── .gitlab-ci.yml            # Pipeline CI/CD (lint, test, build a registry.cabocom.net con tag de rama)
├── Dockerfile                # Multi-stage build con alembic y app copiados al runner
├── docker-compose.yml        # Orquestación con PostgreSQL (red jg_agente_net)
├── .env.example              # Plantilla de variables de entorno
├── pyproject.toml            # Dependencias actualizadas con alembic, langgraph-checkpoint-postgres, psycopg
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
│   │   ├── config.py         # Settings centralizados con async_database_url y sync_database_url
│   │   └── checkpointer.py   # PostgresSaver, MemorySaver, core_checkpoints views
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
│   ├── test_database_migrations.py # Pruebas de migraciones y CRUD asíncrono
│   └── test_checkpointer.py        # Pruebas de integración de checkpointer LangGraph
├── scripts/
│   └── check.sh              # Script unificado de validación (Ruff + MyPy + Pytest)
└── docs/
    └── issues/
        ├── ISSUE-F01-*.md
        ├── ISSUE-F02-*.md
        ├── ISSUE-F03-T01-*.md
        ├── ISSUE-F03-T02-analysis.md
        ├── ISSUE-F03-T02-walkthrough.md
        └── ISSUE-F03-T02-PROJECT_CONTEXT.md
```

---

## 3. Estado de la Fase 03: Persistencia y Checkpointing

- [x] **`ISSUE-F03-T01`**: Configuración de base de datos PostgreSQL y migraciones con Alembic.
- [x] **`ISSUE-F03-T02`**: Configuración de PostgresSaver para checkpoints de LangGraph.
- [ ] **`ISSUE-F03-T03`**: Repositorios de persistencia Core (ExecutionRepository, AuditRepository).
