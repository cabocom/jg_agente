# Sistema de Plugins y Extensibilidad de `jg_agente`

> **Estado del Documento:** ESPECIFICACIÓN TÉCNICA VIVA  
> **Versión:** 1.0.0  
> **Componente:** `jg_agente` — Execution Plane (Plugins Subsystem)  

---

## 1. Visión y Propósito

El Core de `jg_agente` es estrictamente agnóstico a los dominios de aplicación (DevOps, finanzas, mensajería, IoT). Todas las capacidades específicas de dominio, herramientas de interacción con sistemas externos, motores de análisis y modelos de datos especializados se incorporan mediante el subsistema de **Plugins**.

Un plugin es una unidad distribuible e independiente que expone sus capacidades al agente respetando contratos de interfaz estrictos y tipados.

---

## 2. Contratos Base (`app/plugins/base.py`)

### 2.1. Metadatos del Plugin (`PluginMetadata`)

Representa la identidad formal, versión, restricciones de compatibilidad y dependencias de un plugin:

```python
class PluginMetadata(BaseModel):
    name: str                           # Identificador único (slug: 'weather', 'devops')
    version: str                        # Versión semántica (e.g. '1.0.0')
    description: str = ""               # Descripción funcional
    author: str = ""                    # Autor u organización
    jg_agente_version_min: str = "1.0.0" # Compatibilidad mínima requerida con Core
    enabled: bool = True                # Flag de activación
    tags: list[str] = []                # Categorías clasificatorias
    dependencies: list[str] = []        # Plugins requeridos
    config_schema: type[BaseModel] | None = None # Esquema de configuración
    extra: dict[str, Any] = {}          # Metadatos libres
```

### 2.2. Motor de Dominio (`BaseEngine`)

Define la interfaz para componentes de lógica cognitiva o especializada (observadores, planificadores, verificadores):

```python
class BaseEngine(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """Nombre identificador del motor."""
        ...

    @property
    @abstractmethod
    def engine_type(self) -> str:
        """Tipo o rol del motor (e.g. 'observer', 'planner', 'verifier')."""
        ...

    async def startup(self) -> None:
        """Hook opcional de inicialización y adquisición de recursos."""
        pass

    async def shutdown(self) -> None:
        """Hook opcional de liberación de recursos."""
        pass
```

### 2.3. Clase Base `BasePlugin`

Contrato abstracto obligatorio que debe implementar todo plugin de la plataforma:

```python
class BasePlugin(ABC):
    @abstractmethod
    def get_plugin_metadata(self) -> PluginMetadata:
        """Retorna los metadatos canónicos del plugin."""
        ...

    @abstractmethod
    def register_tools(self) -> list[AgentTool]:
        """Retorna la lista de AgentTool provistas para el Core."""
        ...

    @abstractmethod
    def register_engines(self) -> dict[str, BaseEngine]:
        """Retorna motores de dominio mapeados por nombre o rol."""
        ...

    def register_models(self) -> dict[str, type[BaseModel]]:
        """Hook opcional para declarar esquemas Pydantic adicionales."""
        return {}

    async def startup(self) -> None:
        """Inicialización asíncrona durante el boot del agente."""
        pass

    async def shutdown(self) -> None:
        """Liberación asíncrona durante el shutdown del agente."""
        pass

    async def health_check(self) -> dict[str, Any]:
        """Comprobación de operatividad del plugin."""
        return {"status": "ok", "plugin": self.name}
```

---

## 3. Ciclo de Vida de los Plugins

1. **Descubrimiento y Carga:** El agente localiza los plugins (modo local o paquetes instalados vía `entry_points`).
2. **Validación de Compatibilidad:** Se valida que `jg_agente_version_min` satisfaga la versión del Core en ejecución.
3. **Registro de Capacidades:**
   - Invocación de `register_tools()` para exponer herramientas al `CapabilityRegistry`.
   - Invocación de `register_engines()` para registrar motores cognitivos en el grafo.
   - Invocación de `register_models()` para extender el catálogo de datos.
4. **Inicialización (`startup`):** Se invoca concurrentemente `await plugin.startup()` para cada plugin activo durante el arranque del servicio.
5. **Ejecución y Monitoreo (`health_check`):** Los plugins reportan su estado para endpoints de observabilidad.
6. **Apagado Grácil (`shutdown`):** Se invoca `await plugin.shutdown()` al detener el servicio, cerrando conexiones de red, pools o procesos en segundo plano.

---

## 4. Soporte para Gestor de Contexto Asíncrono

`BasePlugin` implementa soporte nativo para el protocolo `async with`:

```python
async with MyPlugin() as plugin:
    # startup() se ejecuta automáticamente
    tools = plugin.register_tools()
    ...
# shutdown() se ejecuta automáticamente al salir del bloque
```

---

## 5. Registro Central de Capacidades (`CapabilityRegistry`)

Ubicado en `app/core/registry.py`, `CapabilityRegistry` consolida el catálogo de capacidades cargadas durante el arranque del agente, aplicando una política de **detección estricta de conflictos** que aborta el boot ante duplicados o inconsistencias:

### 5.1. Detección de Conflictos (`BootConflictError`)

A diferencia de sistemas permisivos que sobrescriben componentes de forma silenciosa, `jg_agente` impone que cualquier colisión en tiempo de arranque sea tratada como un fallo fatal de configuración mediante `BootConflictError`:

1. **Unicidad de Herramientas:** Cada `AgentTool` se indexa por su nombre único (`tool.name`). Si dos herramientas poseen el mismo identificador, el registro falla inmediatamente.
2. **Unicidad de Motores Cognitivos Singleton:** Los motores que intervienen en etapas críticas del ciclo de vida del agente solo admiten **una única implementación activa por rol**:
   - `ObserverEngine` (`engine_type = "observer"`)
   - `PlannerEngine` (`engine_type = "planner"`)
   - `VerifierEngine` (`engine_type = "verifier"`)
   El intento de registrar un segundo motor para cualquiera de estos roles lanza un `BootConflictError` explícito indicando el conflicto.
3. **Motores de Dominio Múltiples:** Los motores con roles no singleton (e.g. `"discovery"`, `"telemetry"`) pueden coexistir siempre que sus nombres identificadores sean disjuntos.

### 5.2. API de Consulta e Integración

- **Herramientas:** `get_tool(name)`, `has_tool(name)`, `list_tools(category, max_risk)`, `get_langchain_tools()`.
- **Motores:** `get_planner()`, `get_observer()`, `get_verifier()`, `get_engine(name)`, `get_engine_by_type(type)`.
- **Plugins:** `register_plugin(plugin)` (registro en cascada de herramientas, motores y modelos), `get_plugin(name)`.
- **Resumen:** `get_capabilities_summary()` para la exposición pública del catálogo en el endpoint `GET /capabilities`.

---

## 6. Gestor de Plugins (`PluginManager`) y Autodescubrimiento

Ubicado en `app/core/plugin_manager.py`, `PluginManager` orquesta el descubrimiento dinámico, la resolución de grafos de dependencia y el ciclo de vida de los plugins.

### 6.1. Mecanismos Duales de Descubrimiento

1. **Modo Distribuido (Producción):**  
   Inspecciona `importlib.metadata.entry_points(group="jg_agente.plugins")`. Cualquier paquete Python instalado vía `pip` que declare este grupo en su `pyproject.toml` es autodescubierto e incorporado al Core sin modificar el código base.
2. **Modo Local (Desarrollo):**  
   Inspecciona rutas locales (`plugins/`) usando `pkgutil.iter_modules()`. Identifica módulos que expongan la convención `PLUGIN_CLASS` o cualquier clase que herede de `BasePlugin`.

### 6.2. Validación de Dependencias y Ordenamiento Topológico

- Cada plugin puede declarar dependencias en `PluginMetadata.dependencies`.
- `PluginManager` construye un grafo dirigido y aplica el **algoritmo de Kahn** para:
  - Validar que todas las dependencias requeridas existan y estén activas (`PluginDependencyError` si falta alguna).
  - Detectar y prevenir dependencias circulares.
  - Computar el orden topológico exacto para inicializar dependencias antes de sus consumidores.

### 6.3. Ciclo de Vida Coordinado

- **`await pm.startup()`:** Inicializa los plugins en orden topológico estricto de dependencias.
- **`await pm.shutdown()`:** Detiene los plugins en **orden inverso** de dependencias, garantizando una liberación ordenada de recursos.
- **`await pm.health_check()`:** Consolida el estado de salud y telemetría de todos los plugins activos.
- **Soporte `async with pm:`** para inicialización y parada garantizada en contextos de ejecución acotados.

---

## 7. Validación en Boot e Integridad de Capacidades

Ubicado en `app/core/boot.py`, el subsistema de arranque realiza una comprobación determinista de coherencia antes de que la aplicación FastAPI acepte tráfico.

### 7.1. Verificación de Integridad (`validate_boot_capabilities`)

Garantiza que el conjunto de capacidades cargadas sea compatible con el perfil configurado del agente:
1. **Plugins Requeridos:** Comprueba que todos los plugins declarados en `settings.REQUIRED_PLUGINS` estén cargados y activos.
2. **Herramientas Obligatorias:** Comprueba que todas las tools declaradas en `settings.REQUIRED_TOOLS` existan en el `CapabilityRegistry`.
3. **Motores Cognitivos Esenciales:** Si el perfil exige planificación (`REQUIRE_PLANNER=True`), observación (`REQUIRE_OBSERVER=True`) o verificación (`REQUIRE_VERIFIER=True`), valida que el motor correspondiente se encuentre registrado.
4. **Integridad Funcional de Tools:** Verifica que cada herramienta disponga de una función ejecutable (`callable(tool.func)`) y categoría válida.

Ante cualquier discrepancia, se lanza un `BootIntegrityError` explícito abortando el arranque de inmediato.

### 7.2. Orquestación en Lifespan y Endpoint `/capabilities`

Durante el evento `lifespan` de FastAPI en `app/main.py`:
- Se invoca `init_agent_capabilities(settings)`, la cual descubre plugins, valida dependencias, verifica colisiones y valida la integridad de arranque.
- Se almacenan `registry` y `plugin_manager` en el estado de la aplicación (`app.state`).
- Se expone el catálogo activo en `GET /capabilities` mediante `registry.get_capabilities_summary()`.



