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
