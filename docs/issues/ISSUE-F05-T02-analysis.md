# Análisis Técnico: ISSUE-F05-T02 — Implementación de nodo base: reason

> **Issue ID:** `ISSUE-F05-T02`  
> **Fase:** `FASE 05`  
> **Componente:** `jg_agente.nodes.reason` / `jg_agente.core.llm`  
> **Fecha:** 4 de septiembre de 2026  
> **Prioridad:** Critical | **Complejidad:** M  
> **Dependencias:** `ISSUE-F05-T01` (GraphBuilder)

---

## 1. Contexto y Objetivos

El nodo cognitivo troncal de razonamiento (`reason`) es el componente de decisión central en la arquitectura LangGraph de `jg_agente`. Su misión es transformar el estímulo inicial (`AgentInput`) y el historial conversacional (`messages`) acumulado en `AgentState` en una decisión operativa ejecutable:
1. Generar llamadas a herramientas estructuradas (`tool_calls`) si la solicitud requiere interacción con el entorno o capacidades externas.
2. Formular una respuesta directa (`AIMessage`) y concluir la interacción si el estímulo puede resolverse conversacionalmente sin invocar herramientas.
3. Desencadenar la etapa de planificación (`plan`) si el estímulo representa una solicitud compleja y existen motores `PlannerEngine` registrados en `CapabilityRegistry`.

---

## 2. Requisitos y Criterios de Aceptación

- **Criterio de Aceptación:** `Nodo reason produce lista de tool calls o respuesta directa a partir de AgentInput y memoria conversacional.`
- **Agnosticismo Radical:** Cero referencias o bifurcaciones acopladas a dominios específicos (`conversational`, `devops`, `telephony`). El nodo inspecciona las capacidades registradas (`registry.get_langchain_tools()`, `registry.get_planner()`) dinámicamente.
- **Enlace Dinámico de Herramientas (Tool Binding):** Si hay herramientas registradas en `CapabilityRegistry`, deben vincularse dinámicamente al LLM (`model.bind_tools(tools)`).
- **Abstracción de Proveedor LLM:** Soporte para múltiples proveedores vía configuración (`LLM_PROVIDER`), incluyendo un `MockChatModel` determinista para testing y entornos desconectados, y `OpenAICompatibleChatModel` (vLLM, Ollama, OpenAI) para producción.
- **Trazabilidad y Auditoría:** Cada invocación del nodo debe emitir un registro estructurado `AuditRecord` en `audit_trail` con métricas de decisión.

---

## 3. Decisiones de Diseño

1. **Gestión de Memoria Conversacional (`messages`):**
   - El nodo preserva la lista histórica de mensajes (`BaseMessage`).
   - Se inyecta un `SystemMessage` con las directrices globales si no existe uno previo.
   - Se añade el prompt del usuario como `HumanMessage` si no ha sido incorporado previamente.
   - El resultado del LLM se concatena como `AIMessage` a través del reducer `add_messages` de LangGraph.

2. **Detección de Saludos e Interacciones Directas:**
   - La función `_is_simple_greeting_or_chat` discrimina estímulos meramente conversacionales o de cortesía frente a solicitudes operativas.
   - Si no se producen `tool_calls` pero hay un motor de planificación disponible y el estímulo es operativo, se transiciona a `action_type = "plan"`.

3. **Arquitectura de LLM Desacoplada (`app/core/llm.py`):**
   - `MockChatModel`: Extiende `BaseChatModel` de LangChain. Permite emparejamiento semántico/léxico con nombres de herramientas para emitir `tool_calls` predictivos en tests unitarios.
   - `OpenAICompatibleChatModel`: Cliente asíncrono sobre `httpx` que mapea el formato de herramientas (`tools`/`tool_calls`) según el estándar OpenAI Function Calling.
   - `get_chat_model()`: Factoría que lee variables de entorno sin dependencias duras de SDKs propietarios.
