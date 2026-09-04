# Contexto de Proyecto: jg_agente

> **Fecha de Actualización:** 4 de septiembre de 2026  
> **Estado Global del Proyecto:** Fases 01, 02 y 03 completadas al 100%.  
> **Próxima Tarea Inmediata:** Inicio de Fase 04 (CapabilityRegistry y Sistema de Plugins Core).  

---

## 1. Resumen Ejecutivo de la Tarea Completada

Se ha implementado el interceptor central de seguridad `SecurityGuard` en `app/security/guard.py`:
- Interceptor previo a la invocación física de cualquier herramienta (`AgentTool`).
- Verificación estricta de permisos (`required_permissions`) frente a los permisos del llamador.
- Detección determinista de inyecciones de comandos shell y Directory Traversal.
- Integración con `SSRFValidator` para bloqueo de URLs e IPs no autorizadas.
- Puerta de enlace Human-In-The-Loop (`REQUIRE_HUMAN_APPROVAL`) para operaciones de riesgo `HIGH` y `CRITICAL`.
- Sanitización de entradas e integración inmutable con `SecurityAuditLogger`.
- 11 tests unitarios nuevos en `tests/test_security_guard.py` (90 tests totales pasando en el proyecto).
- Fase 03 (Persistencia, Checkpointing y Seguridad Base) finalizada al 100%.

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
│   │   ├── config.py               # Configuración centralizada Pydantic
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
│       ├── guard.py                # SecurityGuard (interceptor de ejecución, permisos y HITL)
│       └── ssrf.py                 # SSRFValidator (bloqueo RFC 1918, metadata y loopback)
├── docs/                           # Documentación técnica viva
│   ├── architecture.md             # Visión del Execution Plane y ciclo cognitivo
│   ├── models.md                   # Contratos canónicos I/O, Tools y Estado
│   ├── database.md                 # Persistencia relacional, convención core_ y Alembic
│   ├── checkpointer.md             # Checkpointer LangGraph sobre PostgreSQL
│   ├── security.md                 # SecurityGuard, auditoría inmutable y protección SSRF
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
│   ├── test_ssrf_validator.py
│   └── test_security_guard.py
└── scripts/
    └── check.sh                    # Verificación integral (Ruff + MyPy + Pytest)
```

---

## 3. Estado de la Fase 03: Persistencia y Checkpointing (100% COMPLETADA)

- [x] **`ISSUE-F03-T01`**: Configuración de base de datos PostgreSQL y migraciones con Alembic.
- [x] **`ISSUE-F03-T02`**: Configuración de PostgresSaver para checkpoints de LangGraph.
- [x] **`ISSUE-F03-T03`**: Implementación de SecurityAuditLogger.
- [x] **`ISSUE-F03-T04`**: Implementación de validador de protección SSRF para tools de red.
- [x] **`ISSUE-F03-T05`**: Implementación de SecurityGuard para validación previa a ejecución de tools.
