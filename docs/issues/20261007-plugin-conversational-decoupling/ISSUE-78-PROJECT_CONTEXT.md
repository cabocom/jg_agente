# Contexto de Proyecto: [jg_agente#78] Desacoplamiento y Extracción de jg_plugin_conversational

## 1. Identificación y Metadatos
- **Issue ID:** jg_agente#78
- **Título:** refactor(plugins): desacoplar y extraer jg_plugin_conversational a repositorio independiente
- **Componente:** `jg_agente` (Core) / `jg_plugin_conversational` (Plugin)
- **Tipo:** Architecture / Refactor
- **Prioridad:** High
- **Etiquetas:** architecture, plugins, decoupling, conversational, open-core
- **Peso:** 3

## 2. Antecedentes y Justificación
El principio Open-Core de la plataforma `javiergalvez-ia` exige que el núcleo del agente cognitivo (`jg_agente`) permanezca estrictamente agnóstico a dominios de negocio o casos de uso particulares.

Con anterioridad a esta intervención, el plugin conversacional residía directamente dentro del árbol de código fuente del core (`jg_agente/plugins/jg_plugin_conversational/`), incurriendo en acoplamiento indeseado:
1. `weather.py` importaba de `app.models.tools` (`AgentTool`, `RiskLevel`, `ToolResult`, `ToolType`).
2. `news.py` importaba de `app.models.tools` y de `app.security.ssrf` (`SSRFValidator`, `SSRFValidationError`).
3. `plugin.py` importaba de `app.models.tools` y de `app.plugins.base` (`BaseEngine`, `BasePlugin`, `PluginMetadata`).
4. Las pruebas unitarias importaban directamente `app.core.registry.CapabilityRegistry` y `app.core.plugin_manager.PluginManager`.
5. Ausencia de ciclo de vida, versionado y empaquetado autónomo en GitLab/PyPI.

## 3. Modelo Objetivo
- Extracción de `jg_plugin_conversational` a su propio repositorio git independiente (`gitlab.com:javiergalvez-ia/jg_plugin_conversational`).
- Uso exclusivo de `jg_agente_sdk` (`jg_sdk.contracts`) como Fuente Única de Verdad para contratos y tipos.
- Módulo de blindaje anti-SSRF desacoplado (`ssrf_guard.py`) dentro del propio plugin.
- Pruebas unitarias aisladas con arnés `MockPluginRunner` de `jg_sdk.testing`.
- Registro formal del entry-point `[project.entry-points."jg_agente.plugins"] conversational = "jg_plugin_conversational.plugin:ConversationalPlugin"`.
