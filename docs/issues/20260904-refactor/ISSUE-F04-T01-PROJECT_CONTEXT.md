# Contexto de Proyecto tras ISSUE-F04-T01

> **Fecha:** 2026-09-04  
> **Versión:** 2.6.0  
> **Estado:** Fase 04 Iniciada (1/X completado)  

---

## Componentes Disponibles en `jg_agente`

1. **Bootstrap & CI/CD:** FastAPI, Dockerfile multi-stage, docker-compose local, `.gitlab-ci.yml`.
2. **Modelos Core:** `AgentInput`, `AgentOutput`, `AgentTool`, `ToolResult`, `AgentState`, `PolicyDecision`, `SecurityEvaluationResult`.
3. **Persistencia & Checkpointing:**
   - SQLAlchemy 2.0 async + asyncpg con naming convention estricto `core_*`.
   - Migraciones Alembic (`0001_initial_core_tables.py`).
   - Checkpointer LangGraph (`PostgresSaver`, `MemorySaver`) con vistas actualizables `core_checkpoints`.
4. **Seguridad y Auditoría:**
   - `SecurityAuditLogger`: Registro inmutable no bloqueante en background sobre `core_audit_records`.
   - `SSRFValidator`: Validación de destinos de red, loopback, RFC 1918, metadata cloud y DNS rebinding.
   - `SecurityGuard`: Interceptor central de seguridad previo a `func` (permisos, inyecciones, SSRF, HITL y auditoría).
5. **Plugins Subsystem:**
   - `BasePlugin`: Contrato abstracto con `get_plugin_metadata()`, `register_tools()`, `register_engines()`, `startup()`, `shutdown()`.
   - `PluginMetadata`: Metadatos inmutables y validados.
   - `BaseEngine`: Contrato base para motores de dominio (observer, planner, verifier).

---

## Siguientes Pasos (Fase 04)

- Implementación del registro central de capacidades (`CapabilityRegistry`) para indexar herramientas y motores provistos por plugins.
- Sistema de descubrimiento automático de plugins (`PluginManager` para modo local `plugins/` y entry points).
