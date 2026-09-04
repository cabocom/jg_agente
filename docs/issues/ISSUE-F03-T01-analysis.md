# Análisis Técnico: ISSUE-F03-T01 — Configuración de base de datos PostgreSQL y migraciones con Alembic

> **Issue ID:** ISSUE-F03-T01  
> **Fase:** FASE 03 (Persistencia y Checkpointing)  
> **Prioridad:** High  
> **Complejidad:** M  
> **Estado:** Implementado y Verificado  

---

## 1. Contexto y Objetivos

El Execution Plane (`jg_agente`) requiere persistencia relacional asíncrona para:
1. Registrar el ciclo de vida de las ejecuciones, tiempos de cómputo y estados finales (`core_executions`).
2. Mantener trazas inmutables de auditoría de cada acción, evaluación de seguridad e invocación de herramientas (`core_audit_records`).
3. Preservar una estricta separación de esquemas entre el Core y los Plugins:
   - **Regla de oro:** Todas las tablas y restricciones gestionadas por el Core deben comenzar invariablemente por el prefijo `core_`.
   - **Aislamiento de Plugins:** Alembic debe gestionar exclusivamente las tablas `core_*`, ignorando cualquier tabla de dominio perteneciente a plugins (ej. `devops_*`, `plugin_*`).

---

## 2. Reutilización y Adaptación (Código Origen)

- Se tomaron los parámetros de conectividad a PostgreSQL configurados en `Devops60k/docker-compose.yml` y `.env.example`.
- Se adaptaron los esquemas de persistencia de ejecuciones y auditoría hacia modelos declarativos de SQLAlchemy 2.0 (`Mapped` y `mapped_column`).
- Se implementó la integración nativa de Alembic con motor asíncrono (`async_engine_from_config`) y soporte híbrido para ejecución síncrona/asíncrona (`ThreadPoolExecutor` ante event loops activos de pytest/FastAPI).

---

## 3. Decisiones de Diseño

1. **Convención de Nombres Estricta (`core_naming_convention`):**
   - Se configuró en `MetaData`:
     - Índices: `core_ix_%(column_0_label)s`
     - Claves únicas: `core_uq_%(table_name)s_%(column_0_name)s`
     - Check constraints: `core_ck_%(table_name)s_%(constraint_name)s`
     - Claves foráneas: `core_fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s`
     - Claves primarias: `core_pk_%(table_name)s`
   - Ningún objeto de la base de datos carece del prefijo `core_`.

2. **Filtro de Inclusión en Alembic (`include_object`):**
   - En `alembic/env.py`, la función `include_object` descarta cualquier tabla cuyo nombre no inicie por `core_`.

3. **Migración Inicial (`0001_initial_core`):**
   - Crea `core_executions` y `core_audit_records` con tipos compatibles PostgreSQL / SQLite (`with_variant`).
   - Define índices para búsquedas rápidas por `thread_id`, `status`, `execution_id`, `event_type` y `timestamp`.
   - Clave foránea `core_fk_core_audit_records_execution_id_core_executions` con borrado en cascada (`ON DELETE CASCADE`).

---

## 4. Criterios de Aceptación Verificados

- [x] Motor async SQLAlchemy / asyncpg configurado junto a `async_session_factory` y generador de dependencias.
- [x] Alembic configurado y migración `0001_initial_core` creada y testeada.
- [x] Tablas `core_executions` y `core_audit_records` creadas exitosamente.
- [x] Ningún objeto de BD carece de prefijo `core_`.
- [x] Tests unitarios y de integración de migraciones (upgrade y downgrade) pasando en `tests/test_database_migrations.py`.
