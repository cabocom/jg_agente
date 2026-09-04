# Persistencia de Datos y Migraciones con Alembic

> **Estado del Documento:** ESPECIFICACIÓN TÉCNICA VIVA  
> **Versión:** 2.3.0  
> **Módulo:** `app.db`, `alembic`  

---

## 1. Principio de Aislamiento de Esquemas

En la base de datos de `jg_agente`, todas las tablas, vistas, índices, claves primarias, foráneas y restricciones administradas por el Core cumplen obligatoriamente la convención de prefijos **`core_`**.

### Reglas Clave:
1. **Ningún objeto del Core carece de prefijo `core_`:**
   - Tablas: `core_executions`, `core_audit_records`
   - Vistas: `core_checkpoints`, `core_checkpoint_blobs`, `core_checkpoint_writes`
2. **Aislamiento de Plugins:**
   Las tablas de dominios específicos pertenecientes a plugins (ej. `devops_infra_snapshots`) son gestionadas de forma autónoma por sus respectivos plugins. Alembic está configurado mediante `include_object` para ignorar cualquier objeto de base de datos que no inicie con `core_`.

---

## 2. Convención de Nombres Estricta (`core_metadata`)

Configurada en `app.db.base.core_metadata`:

| Objeto | Patrón de Nombres | Ejemplo |
| :--- | :--- | :--- |
| **Índice (ix)** | `core_ix_%(column_0_label)s` | `core_ix_core_executions_thread_id` |
| **Clave Única (uq)** | `core_uq_%(table_name)s_%(column_0_name)s` | `core_uq_core_executions_execution_id` |
| **Check Constraint (ck)** | `core_ck_%(table_name)s_%(constraint_name)s` | `core_ck_core_executions_status` |
| **Clave Foránea (fk)** | `core_fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s` | `core_fk_core_audit_records_execution_id_core_executions` |
| **Clave Primaria (pk)** | `core_pk_%(table_name)s` | `core_pk_core_executions` |

---

## 3. Modelos ORM del Core

### 3.1 `CoreExecution` (`core_executions`)
Almacena el ciclo de vida de cada ejecución, duraciones y respuestas finales:
- `execution_id` (PK, String 64)
- `thread_id` (Index, String 128)
- `status` (Index, String 32)
- `prompt` (Text)
- `response` (Text, Nullable)
- `parameters` (JSON)
- `data` (JSON, Nullable)
- `user_context` (JSON, Nullable)
- `execution_time_ms` (Float)
- `requires_approval` (Boolean)
- `pending_approval_id` (String 128, Nullable)
- `error` (Text, Nullable)
- `metadata` (JSON)
- `created_at` / `completed_at` (DateTime con timezone)

### 3.2 `CoreAuditRecord` (`core_audit_records`)
Almacena trazas inmutables de auditoría asociadas o desacopladas de las ejecuciones:
- `id` (PK, BigInteger autoincremental)
- `execution_id` (FK a `core_executions.execution_id` con `ON DELETE CASCADE`, Nullable)
- `event_type` (Index, String 64)
- `actor` (String 64)
- `details` (JSON)
- `timestamp` (Index, DateTime UTC)

---

## 4. Gestión de Migraciones con Alembic

Las migraciones se ejecutan de manera asíncrona mediante `async_engine_from_config` en `alembic/env.py`.

```bash
# Aplicar migraciones a la última versión
alembic upgrade head

# Revertir última migración
alembic downgrade -1
```
