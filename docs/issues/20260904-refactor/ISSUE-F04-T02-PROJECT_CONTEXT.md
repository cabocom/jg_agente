# Contexto de Proyecto tras ISSUE-F04-T02

> **Fecha:** 2026-09-04  
> **Versión:** 2.7.0  
> **Estado:** Fase 04 Avanzada (2/X completados)  

---

## Capacidades Disponibles en `jg_agente`

1. **Bootstrap & CI/CD:** FastAPI, Dockerfile multi-stage, docker-compose local, `.gitlab-ci.yml`.
2. **Modelos Core:** `AgentInput`, `AgentOutput`, `AgentTool`, `ToolResult`, `AgentState`, `PolicyDecision`, `SecurityEvaluationResult`.
3. **Persistencia & Checkpointing:**
   - SQLAlchemy 2.0 async + asyncpg con convención estricta `core_*`.
   - Migraciones Alembic (`0001_initial_core_tables.py`).
   - Checkpointer LangGraph (`PostgresSaver`, `MemorySaver`) con vistas `core_checkpoints`.
4. **Seguridad y Auditoría:**
   - `SecurityAuditLogger`: Registro inmutable asíncrono no bloqueante en `core_audit_records`.
   - `SSRFValidator`: Bloqueo de loopback, redes privadas RFC 1918 y metadata de nubes.
   - `SecurityGuard`: Interceptor central de seguridad previo a `func` (permisos, inyecciones, SSRF, HITL y auditoría).
5. **Plugins Subsystem & Registro:**
   - `BasePlugin`: Contrato abstracto para plugins con ciclo de vida asíncrono.
   - `PluginMetadata`: Metadatos inmutables de plugins.
   - `BaseEngine`, `ObserverEngine`, `PlannerEngine`, `VerifierEngine`: Contratos para motores cognitivos.
   - `CapabilityRegistry`: Catálogo centralizado con detección estricta de conflictos (`BootConflictError`), indexación única de herramientas y validación de motores singleton.

---

## Siguientes Pasos (Fase 04)

- Implementación del cargador y gestor de plugins (`PluginManager` para descubrimiento dinámico vía `plugins/` y `entry_points`).
- Carga de plugins y exposición en el ciclo de vida del agente.
