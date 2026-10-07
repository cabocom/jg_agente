# Análisis Técnico: [jg_agente#78] Desacoplamiento y Extracción de jg_plugin_conversational

## 1. Diagnóstico de Acoplamiento y Dependencias Directas

Al auditar `jg_agente/plugins/jg_plugin_conversational/`, se constataron las siguientes dependencias rígidas hacia el núcleo de `jg_agente`:

```text
jg_agente/plugins/jg_plugin_conversational/
├── weather.py   --> from app.models.tools import AgentTool, RiskLevel, ToolResult, ToolType
├── news.py      --> from app.models.tools import ...
│                --> from app.security.ssrf import SSRFValidator, SSRFValidationError, ...
├── plugin.py    --> from app.models.tools import AgentTool
│                --> from app.plugins.base import BaseEngine, BasePlugin, PluginMetadata
└── tests/
    ├── test_plugin.py       --> from app.core.plugin_manager import PluginManager
    │                        --> from app.core.registry import CapabilityRegistry
    ├── test_weather_tool.py --> from app.core.registry import CapabilityRegistry
    └── test_news_tool.py    --> from app.core.registry import CapabilityRegistry
```

### Impactos del Diseño Previo
- **Violación de Inversión de Dependencias (DIP):** Un plugin (módulo periférico) dependía de la implementación concreta del core en lugar de abstracciones normativas del SDK.
- **Imposibilidad de Distribución Externa:** El paquete no podía empaquetarse ni distribuirse en PyPI o GitLab Package Registry sin arrastrar el código entero de `jg_agente`.
- **Fragilidad en CI/CD:** Cualquier modificación de dependencias o tests del plugin requería ejecutar la suite monolítica del core.

## 2. Estrategia de Refactorización

1. **Sustitución de Contratos por SDK:**
   Todos los modelos canónicos (`AgentTool`, `RiskLevel`, `ToolResult`, `ToolType`, `BasePlugin`, `PluginMetadata`, `BaseEngine`) provienen exclusivamente de `jg_sdk.contracts` (`jg-agente-sdk>=1.0.0`).
2. **Mitigación Anti-SSRF Autónoma (`ssrf_guard.py`):**
   Para evitar arrastrar `app.security.ssrf` (que a su vez importa `app.core.config.settings`), se encapsuló un helper autónomo `SSRFGuard` que valida rangos privados (RFC 1918, RFC 4193, 169.254.0.0/16, loopbacks) e implementa transporte HTTP con DNS pinning.
3. **Aislamiento de la Suite de Pruebas:**
   Reemplazo de `CapabilityRegistry` y `PluginManager` en los tests por `MockPluginRunner` de `jg_sdk.testing`.
4. **Scaffolding e Integración Global:**
   Creación de repositorio independiente en `/Users/javiergalvez/Documents/Code/javiergalvez-ia/jg_plugin_conversational`, montaje en `docker-compose.yml`, exclusión en raíz `.gitignore` y actualización de scripts unificados de verificación.
