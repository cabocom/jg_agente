# Análisis Técnico: [ISSUE-AGENT-006] Semántica y propagación de errores en persistencia de ejecuciones

## 1. Diagnóstico del Estado Previo
En la implementación previa de `app/api/executions.py`:
- `_persist_or_update_execution` envolvía el bloque de base de datos en:
  ```python
  except Exception as exc:
      with contextlib.suppress(Exception):
          await db.rollback()
      logger.warning(
          "No se pudo persistir en core_executions (%s). Continuando en memoria: %s",
          input_data.execution_id,
          exc,
      )
      return None
  ```
- Este patrón presentaba dos fallas de diseño:
  1. **Silenciamiento con retorno `None`:** Al retornar `None` sin elevar una excepción, los puntos de llamada asumían que la función había finalizado normalmente o no distinguían entre ausencia de registro previo y fallo catastrófico de almacenamiento.
  2. **Severidad incorrecta y bloques mudos:** El fallo de escritura en la base de datos se catalogaba como `logger.warning`. Peor aún, en la captura de fallos no controlados del grafo (líneas 357-358), el bloque de persistencia contenía `except Exception: pass`, ignorando totalmente si la grabación de un error fatal del agente fallaba a su vez.
- La estructura de respuesta `AgentOutput` no informaba en ningún campo si la ejecución había sido persistida en PostgreSQL o si existía una degradación en la capa de persistencia.

## 2. Solución Diseñada

### 2.1 Creación de `PersistenceError`
Se introdujo la excepción específica en `app/db/exceptions.py`:
```python
class PersistenceError(Exception):
    """Excepción tipada elevada ante fallos en operaciones de persistencia de base de datos."""
    def __init__(self, message: str, original_error: Any = None) -> None:
        super().__init__(message)
        self.original_error = original_error
```
Re-exportada en `app/db/__init__.py`.

### 2.2 Modelado Tipado de Metadatos de Persistencia
En `app/models/io.py`:
```python
class PersistenceStatus(StrEnum):
    PERSISTED = "persisted"
    DEGRADED = "degraded"
    FAILED = "failed"

class PersistenceMetadata(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")
    status: PersistenceStatus = Field(default=PersistenceStatus.PERSISTED)
    persisted: bool = Field(default=True)
    error: str | None = Field(default=None)
    error_type: str | None = Field(default=None)
```

### 2.3 Refactorización de `_persist_or_update_execution`
- Se eliminó el retorno silencioso de `None`.
- Ante cualquier fallo durante `db.execute`, `db.add`, `db.commit` o `db.refresh`:
  - Se ejecuta `await db.rollback()`.
  - Se emite `logger.error("Fallo crítico al persistir ejecución '%s' en core_executions: %s", input_data.execution_id, exc, exc_info=True)`.
  - Se eleva `PersistenceError(..., original_error=exc) from exc`.

### 2.4 Propagación Tipada en Orquestadores
- **`execute_graph_pipeline`:**
  - En los caminos de interrupción HITL, finalización normal y captura de excepciones no controladas:
    - Éxito: inyecta `PersistenceMetadata(status=PersistenceStatus.PERSISTED, persisted=True)`.
    - Fallo (`PersistenceError` / `Exception`): registra `logger.error` e inyecta `PersistenceMetadata(status=PersistenceStatus.DEGRADED, persisted=False, error=str(db_err), error_type=type(db_err).__name__)`.
    - Se eliminó el bloque `except Exception: pass`.
- **`trigger_execution`:**
  - Envuelve el registro inicial en bloque protegido.
  - Asigna `input_data.metadata["persistence"]` con el estado inicial persistido o degradado.
- **`_resolve_hitl_execution`:**
  - Gestiona la actualización de persistencia tras aprobación/rechazo humano, adjuntando metadatos tipados y registrando `logger.error` ante eventualidades de red o base de datos.
