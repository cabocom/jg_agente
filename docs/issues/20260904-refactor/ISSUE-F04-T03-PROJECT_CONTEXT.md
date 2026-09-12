# Contexto de Proyecto tras ISSUE-F04-T03

> **Fecha:** 2026-09-04  
> **Versión:** 2.8.0  
> **Estado:** Fase 04 Avanzada (3/X completados)  

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
   - `SSRFValidator`: Bloqueo de loopback, RFC 1918 y metadata de cloud providers.
   - `SecurityGuard`: Interceptor central de seguridad previo a `func` (permisos, inyecciones, SSRF, HITL y auditoría).
5. **Plugins Subsystem & Registro:**
   - `BasePlugin`: Contrato canónico para plugins.
   - `PluginMetadata`: Metadatos de plugins y dependencias.
   - `BaseEngine`, `ObserverEngine`, `PlannerEngine`, `VerifierEngine`: Contratos para motores de dominio.
   - `CapabilityRegistry`: Catálogo centralizado con detección estricta de conflictos (`BootConflictError`).
   - `PluginManager`: Autodescubrimiento dual (entry points + módulos locales), validación y ordenamiento topológico de dependencias, e integración con `CapabilityRegistry`.

---

## Siguientes Pasos (Fase 04 / Fase 05)

- Culminar la Fase 04 con herramientas base o interfaces auxiliares si aplica, o avanzar a la **Fase 05** (Ensamblado del Grafo LangGraph con nodos `reason`, `execute`, `conclude`).
