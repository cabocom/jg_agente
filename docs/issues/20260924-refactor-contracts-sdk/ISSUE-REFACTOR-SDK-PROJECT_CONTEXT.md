# Contexto de Proyecto: [REFACTOR-SDK-001] Integración Canónica de Contratos Core desde jg_agente_sdk

## 1. Identificación y Estado
- **Issue ID:** REFACTOR-SDK-001
- **Módulo Afectado:** `app.models.tools`, `app.plugins.base`, `tests/`
- **Componentes:** `jg_agente` (Motor / Execution Plane) y `jg_agente_sdk` (SDK de Plugins)
- **Prioridad:** High / Arquitectura y Mantenibilidad
- **Complejidad Estimada:** M
- **Estado:** Implementado y Verificado (Listo para Commit)

## 2. Alineación Arquitectónica y Motivación
Históricamente, los contratos de herramientas (`AgentTool`, `ToolResult`, `RiskLevel`, `ToolType`) y plugins (`BasePlugin`, `BaseEngine`, `PluginMetadata`) se definían de forma duplicada e independiente tanto en `jg_agente/app/models/tools.py` como en `jg_agente_sdk/jg_sdk/contracts.py`.

Esta duplicidad generaba riesgos severos:
1. **Divergencia de Esquemas (Contract Drift):** Cualquier modificación, campo añadido o cambio de validación en el agente central requería sincronización manual en el SDK.
2. **Fragilidad de Pruebas Cruzadas:** Comparar estructuras entre carpetas hermanas mediante `sys.path` rompía los principios de desacoplamiento e impedía la ejecución en entornos de CI/CD aislados (GitLab CI).
3. **Violación del Principio de Fuente Única de Verdad (SSOT):** Los contratos públicos que deben respetar los desarrolladores de plugins pertenecen conceptualmente al SDK, no al motor interno.

### Solución Arquitectónica Adoptada (Opción A):
- **Dirección de Dependencias Unidireccional:** El SDK (`jg_agente_sdk`) es ultra-ligero y define los contratos canónicos libres de dependencias complejas (cero LangChain, LangGraph o FastAPI). El agente central (`jg_agente`) consume e instala el SDK.
- **Especialización Mediante Herencia Limpia:** `app.models.tools.AgentTool` hereda de `jg_sdk.contracts.AgentTool`, preservando todos los campos, validadores y lógica de ejecución/compensación del SDK, y añadiendo únicamente el adaptador nativo a LangChain (`as_langchain_tool`).
- **Cumplimiento PEP 561:** Se añade el marcador `py.typed` al SDK para garantizar verificación estricta de tipos con MyPy en el Core.
- **Aislamiento de CI/CD:** El test de deriva `tests/test_contracts_drift.py` se mantiene comentado y documentado hasta que ambos repositorios sincronicen sus artefactos mediante el registro de paquetes o token de despliegue en GitLab.

## 3. Criterios de Aceptación Cumplidos
- `app/models/tools.py` importa `RiskLevel`, `ToolResult`, `ToolType` y `AgentTool` (base) directamente de `jg_sdk.contracts`.
- `AgentTool` conserva compatibilidad 100% hacia atrás con el motor LangGraph mediante `as_langchain_tool()`.
- `jg_sdk` expone `py.typed` y se registra en `package-data` de su `pyproject.toml`.
- La suite completa de verificación `./check_unit.sh` pasa al 100% (`jg_agente`, `jg_dashboard` y `jg_agente_sdk`).
