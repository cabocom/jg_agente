# Walkthrough: ISSUE-F03-T02 — Integración de Checkpointer LangGraph sobre PostgreSQL (PostgresSaver)

> **Issue ID:** ISSUE-F03-T02  
> **Fase:** FASE 03 (Persistencia y Checkpointing)  
> **Resultado:** Éxito (52 tests pasando, MyPy strict 0 errores, Ruff limpio)  

---

## 1. Resumen de Cambios

En este issue se implementó la persistencia de checkpoints para LangGraph en PostgreSQL mediante `PostgresSaver`, integrando vistas con prefijo `core_` y habilitando el ciclo completo de congelación, pausado HITL e reanudación de ejecución a partir del `thread_id`.

### Archivos Afectados

- **`pyproject.toml`**: Incorporación de dependencias `langgraph-checkpoint-postgres>=2.0.0` y `psycopg[binary,pool]>=3.2.0`.
- **`app/core/checkpointer.py`**:
  - `ensure_core_checkpoint_views(conn)`: Creación automática de vistas actualizables `core_checkpoints`, `core_checkpoint_blobs`, `core_checkpoint_writes`.
  - `get_default_serializer()`: Instanciación de `JsonPlusSerializer` con lista blanca estricta `STATE_ALLOWED_CLASSES`.
  - `get_postgres_checkpointer()`: Configuración de `PostgresSaver` respaldado por `psycopg_pool.ConnectionPool` (`dict_row`, `open=True`).
  - `get_memory_checkpointer()`: Checkpointer volátil para tests rápidos.
  - `get_checkpointer()`: Factory principal con fallback seguro.
- **`tests/test_checkpointer.py`**:
  - `TestMemoryCheckpointer`: Tests de fábrica y fallback en memoria.
  - `TestPostgresCheckpointerIntegration`:
    - Creación e introspección de la vista `core_checkpoints`.
    - Flujo end-to-end de LangGraph con nodos `reason` -> `approval` -> `execute`.
    - Interrupción antes de `execute` simulando aprobación humana requerida.
    - Verificación física de registros de checkpoint en `core_checkpoints`.
    - Reanudación del hilo (`invoke(None, config=thread_config)`) completando la ejecución y verificando la acumulación de estado (`messages` y `audit_trail`).

---

## 2. Evidencia de Ejecución

### Ejecución de Linter, Tipado y Suite de Tests (`./scripts/check.sh`)

```bash
========================================
🔍 Ejecutando verificación de código...
========================================

1️⃣  [Ruff] Análisis de formato y linter...
All checks passed!
21 files already formatted

2️⃣  [MyPy] Chequeo estático de tipos estricto...
Success: no issues found in 21 source files

3️⃣  [Pytest] Ejecución de suite de tests...
....................................................                     [100%]
52 passed in 0.63s

========================================
✅ ¡Todas las comprobaciones pasaron con éxito!
========================================
```

---

## 3. Próximos Pasos

Continuar con la persistencia relacional en **`[ISSUE-F03-T03]`**:
- Implementar los repositorios asíncronos del Core (`ExecutionRepository` y `AuditRepository`) que encapsulan las operaciones CRUD sobre `core_executions` y `core_audit_records`.
