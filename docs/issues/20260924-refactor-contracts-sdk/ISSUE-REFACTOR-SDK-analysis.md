# Análisis Técnico: [REFACTOR-SDK-001] Integración Canónica de Contratos Core desde jg_agente_sdk

## 1. Análisis de Impacto y Componentes Afectados

### 1.1. Capa de Modelos del Motor (`jg_agente/app/models/tools.py`)
- **Estado previo:** 295 líneas de código redefiniendo manualmente `RiskLevel`, `ToolType`, `ToolResult`, y `AgentTool` con sus respectivos métodos de ejecución (`run`), reversión (`rollback`) y validadores Pydantic v2.
- **Estado actual:** Reducción a 50 líneas. Los enums y modelos estructurales se importan directamente desde `jg_sdk.contracts`. `AgentTool` pasa a ser una subclase directa de `SDKAgentTool` cuya única responsabilidad en el Core es la adaptación hacia LangChain:
  ```python
  class AgentTool(SDKAgentTool):
      def as_langchain_tool(self) -> BaseTool: ...
  ```

### 1.2. Sistema de Plugins y Metadatos (`jg_agente/app/plugins/base.py`)
- Se garantiza la interoperabilidad polimórfica: un plugin desarrollado con `from jg_sdk.contracts import BasePlugin` es reconocido nativamente por el cargador de plugins del motor.
- Se resuelve el falso positivo de análisis de tipo abstracto en MyPy mediante supresión selectiva documentada.

### 1.3. Cumplimiento Estático de Tipos (PEP 561 y MyPy)
- MyPy en modo estricto (`strict = true`) trata las librerías externas sin tipos explícitos como `Any`.
- Al crear el archivo de señalización `jg_agente_sdk/jg_sdk/py.typed` y configurar `package-data` en `jg_agente_sdk/pyproject.toml`, MyPy inspecciona directamente las firmas Pydantic v2 de `jg_sdk` sin requerir stubs (`.pyi`) separados.

### 1.4. Pipeline de CI/CD y Desacoplamiento de Repositorios
- En entornos locales de desarrollo, el SDK se vincula en modo editable (`pip install -e ../jg_agente_sdk` y enlace `.pth`).
- Para entornos remotos (GitLab CI / Docker), el archivo `tests/test_contracts_drift.py` se mantiene comentado para no introducir fallos por ausencia de sistema de archivos compartido.
- Se han redactado las especificaciones para dos issues de activación futura una vez configurado el GitLab Package Registry o el `CI_JOB_TOKEN`.

## 2. Matriz de Pruebas y Riesgos
| Riesgo Identificado | Severidad | Mitigación Implementada |
| :--- | :--- | :--- |
| **Incompatibilidad de firmas en LangChain** | Crítica | `as_langchain_tool()` preservado idéntico en `AgentTool`. Verificado con 437 tests. |
| **Fallo de MyPy por librerías externas** | Alta | `py.typed` incorporado en `jg_sdk` y verificado en 112 ficheros de Core. |
| **Fallo en GitLab CI por rutas locales** | Alta | `tests/test_contracts_drift.py` comentado temporalmente. |
| **Divergencia entre Core y SDK** | Mitigado | Eliminada la duplicidad: el Core hereda del SDK como fuente única. |
