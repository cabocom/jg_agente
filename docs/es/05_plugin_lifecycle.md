# 05. Ciclo de Vida y Ecosistema de Plugins (`jg_agente`)

[← Volver al README](../README.md) | [← 04. Persistencia](04_persistence_state.md) | [06. API REST →](06_api_reference.md)

---

## 1. Desacoplamiento de Capacidades

El runtime de `jg_agente` es agnóstico a cualquier caso de uso específico. Las capacidades operativas (herramientas de DevOps, consultas meteorológicas, datos abiertos o flujos conversacionales) se implementan mediante **plugins modulares**.

Todos los plugins implementan la interfaz `BasePlugin` provista por el SDK canónico (`jg_agente_sdk`).

---

## 2. Estructura de un Plugin (`BasePlugin`)

```python
from jg_sdk.contracts import BasePlugin, PluginMetadata, AgentTool, BaseEngine

class CustomPlugin(BasePlugin):
    def get_plugin_metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="jg_plugin_custom",
            version="1.0.0",
            description="Plugin de ejemplo para el ecosistema jG",
            author="Javier Gálvez",
            tags=["custom", "example"],
        )

    def register_tools(self) -> list[AgentTool]:
        return [my_tool]

    def register_engines(self) -> dict[str, BaseEngine]:
        return {"custom_observer": my_observer_engine}

    async def startup(self) -> None:
        """Inicializa conexiones de red o pools de recursos."""
        pass

    async def shutdown(self) -> None:
        """Cierra conexiones y libera recursos limpiamente."""
        pass

    async def health_check(self) -> dict[str, Any]:
        """Informa del estado de operatividad de sus servicios externos."""
        return {"status": "ok"}
```

---

## 3. Descubrimiento y Resolución de Precedencia (`PluginManager`)

`PluginManager` (`app/core/plugin_manager.py`) implementa un pipeline riguroso de autodescubrimiento local y distribuido:

### 3.1 Precedencia y Estrategia de Descubrimiento
El escaneo se ejecuta en dos fases secuenciales:

1. **Autodescubrimiento Local por Directorio (`discover_local_plugins`):**
   - Escanea el directorio configurado en `PLUGINS_DIR` (por defecto `plugins/`). Añade la ruta a `sys.path`.
   - Por cada paquete o módulo encontrado, evalúa la siguiente precedencia:
     1. **Submódulo explícito:** Intenta importar `{modulo}.plugin` buscando la variable `PLUGIN_CLASS` (debe ser subclase de `BasePlugin`).
     2. **Variable de módulo raíz:** Si no existe `.plugin`, importa `{modulo}` y busca `PLUGIN_CLASS`.
     3. **Inspección de miembros:** Si no existe `PLUGIN_CLASS`, inspecciona los miembros del módulo en busca de la primera clase exportada que herede de `BasePlugin`.
2. **Descubrimiento Distribuido vía Entry Points (`discover_entrypoints`):**
   - Inspecciona el grupo estándar `jg_agente.plugins` en el entorno virtual activo:
     ```toml
     [project.entry-points."jg_agente.plugins"]
     datosgob = "jg_plugin_datosgob.plugin:DatosGobPlugin"
     ```
   - Carga e instancia dinámicamente las clases referenciadas, validando que sean conformes a `BasePlugin`.

### 3.2 Filtrado Selectivo (`ENABLED_PLUGINS`)
- Si se define `ENABLED_PLUGINS` (ej. `ENABLED_PLUGINS="jg_plugin_datosgob,jg_plugin_mock_api"`), el gestor descarta cualquier plugin descubierto cuyo nombre canónico o módulo no figure en dicha lista.
- Si no está definida o contiene `*` o `all`, se activan todos los plugins descubiertos.

---

## 4. Resolución Topológica de Dependencias (Algoritmo de Kahn)

Los plugins pueden declarar dependencias explícitas hacia otros plugins en sus metadatos (`metadata.dependencies = ["jg_plugin_base", "jg_plugin_auth"]`).

`PluginManager._resolve_dependencies_and_order()` construye un Grafo Acíclico Dirigido (DAG) y ejecuta el **Algoritmo de Kahn**:

```text
┌────────────────────────────────────────────────────────┐
│           Construcción del Grafo de Dependencias       │
│               in_degree[plugin] & adjacency            │
└──────────────────────────┬─────────────────────────────┘
                           │
             ¿Dependencia no instalada?
             ├── SÍ ──► Lanza PluginDependencyError
             │          (Dependencia insatisfecha)
             │
             └── NO
                  │
                  ▼
         Cola con in_degree == 0 (Sin dependencias)
                  │
                  ▼
         Bucle de Kahn: Extraer nodo y decrementar
         in_degree de los plugins que dependen de él
                  │
                  ▼
         ¿Nodos ordenados != Total plugins?
         ├── SÍ ──► Lanza PluginDependencyError
         │          (Dependencia circular detectada)
         │
         └── NO ──► Orden Topológico de Carga Establecido
```

- **Validación de Dependencias Ausentes:** Si un plugin requiere una dependencia no cargada, el gestor aborta el arranque con `PluginDependencyError`.
- **Detección de Ciclos:** Si existen dependencias circulares (ej. A -> B -> A), el contador de Kahn no alcanza el total de plugins y se lanza `PluginDependencyError` detallando los módulos bloqueados.

---

## 5. Fases del Ciclo de Vida en el Contenedor

1. **Boot (`app/main.py:lifespan`):**
   - Descubrimiento local y por entry points.
   - Resolución topológica de dependencias mediante Algoritmo de Kahn (`load_order`).
   - Registro de herramientas y motores en `CapabilityRegistry`.
   - Validación de integridad Fail-Fast (`validate_boot_capabilities()`).
   - Compilación del grafo LangGraph en `GraphBuilder`.
2. **Startup (`plugin_manager.startup()`):**
   - Se invoca `await plugin.startup()` siguiendo estrictamente el **orden topológico** (`self._load_order`). Las dependencias base siempre se inicializan antes que los plugins que dependen de ellas.
3. **Runtime:**
   - Las herramientas se invocan a demanda en el nodo `execute` bajo el control de `SecurityGuard`.
   - La telemetría periódica (`/health`) consulta concurrentemente `await plugin.health_check()`.
4. **Shutdown Limpio en Orden Inverso (`plugin_manager.shutdown()`):**
   - Al recibir señales SIGTERM/SIGINT, se invoca `await plugin.shutdown()` en **orden inverso al de dependencias** (`reversed(self._load_order)`).
   - Los plugins de mayor nivel liberan sus recursos antes de que se desconecten los plugins base de los que dependen.

---

## 5. Navegación

- [← Anterior: 04. Persistencia, Estado y Checkpointing](04_persistence_state.md)
- [Índice General](../README.md)
- [Siguiente: 06. Referencia de API REST Privada →](06_api_reference.md)
