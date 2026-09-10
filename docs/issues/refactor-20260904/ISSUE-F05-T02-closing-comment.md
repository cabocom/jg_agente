### Resumen de Implementación — ISSUE-F05-T02

Se ha completado la implementación del nodo cognitivo troncal de deliberación `reason_node` en LangGraph para `jg_agente` con soporte para modelos de lenguaje configurables, gestión dinámica de capacidades y corrección del empaquetado de setuptools para CI/CD.

#### 1. Componentes Desarrollados y Modificados
- **`app/nodes/reason.py` & `app/nodes/__init__.py`:**
  - Función asíncrona `reason_node(state, registry, llm, system_prompt)`.
  - Reconstrucción y enriquecimiento de memoria conversacional (`SystemMessage`, `HumanMessage`, `AIMessage`).
  - Vinculación dinámica de herramientas (`model.bind_tools()`) a partir de `CapabilityRegistry.get_langchain_tools()`.
  - Clasificación agnóstica de acción en `IntentModel`:
    - `action_type = "act"` si el modelo emite `tool_calls`.
    - `action_type = "plan"` si no hay herramientas directas pero existe un `PlannerEngine` registrado y la tarea es operativa.
    - `action_type = "conclude"` ante saludos o respuestas directas textuales.
  - Emisión de auditoría estructurada `reasoning_completed` en `audit_trail`.
- **`app/core/llm.py` & `app/core/config.py`:**
  - `MockChatModel`: Implementación determinista de `BaseChatModel` con auto-generación de llamadas a herramientas según léxico para tests locales y CI/CD sin consumo de tokens ni latencia externa.
  - `OpenAICompatibleChatModel`: Cliente HTTP asíncrono sobre `httpx` compatible con endpoints estándar (OpenAI, vLLM, Ollama, LiteLLM) con mapeo estricto de esquemas de funciones y herramientas.
  - `get_chat_model()`: Factoría desacoplada gobernada por variables de entorno (`LLM_PROVIDER`, `LLM_MODEL`, `LLM_BASE_URL`, etc.).
- **`app/core/graph.py`:**
  - Integración de `reason_node` como implementación por defecto del nodo `reason` en `GraphBuilder`.
- **`pyproject.toml` & `.gitignore`:**
  - Configuración explícita de `tool.setuptools.packages.find` para resolver la construcción del wheel en pipelines de CI/CD.
- **`tests/test_node_reason.py`:**
  - Suite de 8 tests unitarios e integrados validando tool calls, respuestas directas, preservación de memoria conversacional y ejecución dentro del grafo LangGraph compilado.

#### 2. Validación y Métricas de Calidad
- `./scripts/check.sh`: **100% verde**.
  - **Ruff:** Formato y linter conformes en los 43 archivos.
  - **MyPy:** Tipado estricto completado con 0 errores en 43 archivos.
  - **Pytest:** 143 pruebas pasando satisfactoriamente.

#### 3. Cumplimiento de Criterios de Aceptación
- [x] **Producción de lista de tool calls o respuesta directa:** Verificado con tests unitarios (`test_reason_node_with_tool_call_emits_act_intent` y `test_reason_node_direct_response_emits_conclude_intent`).
- [x] **Memoria conversacional:** Reconstruye e inyecta la secuencia en `state["messages"]`.
- [x] **Agnosticismo radical:** Cero bifurcaciones por tipo de agente o dominio.
- [x] **Trazabilidad:** Registro inmutable emitido en `audit_trail`.

/close
