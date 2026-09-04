# Contexto de Proyecto: jg_agente

> **Fecha de Actualización:** 4 de septiembre de 2026  
> **Estado Global del Proyecto:** Fase 01 y Fase 02 completadas (100%), Fase 03 en progreso con `ISSUE-F03-T01`, `ISSUE-F03-T02`, `ISSUE-F03-T03` e `ISSUE-F03-T04` completados.  
> **Próxima Tarea Inmediata:** Continuación de la Fase 03 / Repositorios Core o inicio de Fase 04.  

---

## 1. Resumen Ejecutivo de la Tarea Completada

Se ha implementado el módulo de seguridad `SSRFValidator` en `app/security/ssrf.py`:
- Bloqueo determinista de loopback (`127.0.0.1`), metadata de instancias cloud (`169.254.169.254`) y redes privadas RFC 1918 / RFC 4193.
- Protección contra DNS rebinding mediante resolución y verificación de todas las IPs devueltas por el resolver.
- Soporte para allowlists por configuración (`SSRF_ALLOWED_HOSTS`, `SSRF_ALLOWED_NETWORKS`) y flag `SSRF_ALLOW_PRIVATE_NETWORKS`.
- Método de inspección para herramientas con red `validate_tool_arguments_for_ssrf`.
- Actualización de `docs/security.md` y `README.md`.
- 18 tests unitarios nuevos en `tests/test_ssrf_validator.py` (79 tests totales pasando).

---

## 2. Estado Actual del Repositorio

```text
jg_agente/
├── .gitlab-ci.yml                  # Pipeline CI/CD a registry.cabocom.net
├── Dockerfile                      # Multi-stage build optimizado
├── docker-compose.yml              # Orquestación local con PostgreSQL
├── .env.example                    # Plantilla de variables de entorno
├── pyproject.toml                  # Dependencias y herramientas
├── README.md                       # Documentación principal del repositorio
├── alembic.ini                     # Configuración de migraciones
├── alembic/
│   ├── env.py                      # Entorno async de Alembic con filtro core_
│   └── versions/
│       └── 0001_initial_core_tables.py # Migración inicial
├── app/
│   ├── __init__.py                 # Versión del paquete
│   ├── main.py                     # Bootstrap FastAPI y ciclo de vida
│   ├── core/
│   │   ├── config.py               # Configuración centralizada Pydantic con SSRF_*
│   │   └── checkpointer.py         # PostgresSaver, MemorySaver y vistas core_checkpoints
│   ├── db/
│   │   ├── base.py                 # DeclarativeBase y convención estricta core_
│   │   ├── models.py               # Modelos ORM: CoreExecution y CoreAuditRecord
│   │   └── session.py              # async_engine y factoría de sesiones asyncpg
│   ├── models/
│   │   ├── io.py                   # Contratos AgentInput y AgentOutput
│   │   ├── state.py                # AgentState, PolicyDecision, SecurityEvaluationResult
│   │   └── tools.py                # Contratos AgentTool y ToolResult
│   └── security/
│       ├── audit.py                # SecurityAuditLogger (persistencia no bloqueante)
│       └── ssrf.py                 # SSRFValidator (bloqueo RFC 1918, metadata y loopback)
├── docs/                           # Documentación técnica viva
│   ├── architecture.md             # Visión del Execution Plane y ciclo cognitivo
│   ├── models.md                   # Contratos canónicos I/O, Tools y Estado
│   ├── database.md                 # Persistencia relacional, convención core_ y Alembic
│   ├── checkpointer.md             # Checkpointer LangGraph sobre PostgreSQL
│   ├── security.md                 # Seguridad, auditoría inmutable y protección SSRF
│   └── issues/                     # Trazabilidad técnica por issue
├── tests/                          # Suite integral de pruebas (Unit + Integration)
│   ├── test_bootstrap.py
│   ├── test_health_endpoint.py
│   ├── test_io_models.py
│   ├── test_tool_models.py
│   ├── test_agent_state.py
│   ├── test_database_migrations.py
│   ├── test_checkpointer.py
│   ├── test_security_audit.py
│   └── test_ssrf_validator.py
└── scripts/
    └── check.sh                    # Verificación integral (Ruff + MyPy + Pytest)
```

---

## 3. Estado de la Fase 03: Persistencia y Checkpointing

- [x] **`ISSUE-F03-T01`**: Configuración de base de datos PostgreSQL y migraciones con Alembic.
- [x] **`ISSUE-F03-T02`**: Configuración de PostgresSaver para checkpoints de LangGraph.
- [x] **`ISSUE-F03-T03`**: Implementación de SecurityAuditLogger.
- [x] **`ISSUE-F03-T04`**: Implementación de validador de protección SSRF para tools de red.
