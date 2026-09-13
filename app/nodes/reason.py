"""Nodo cognitivo troncal de razonamiento (reason) para jg_agente.

Procesa el estímulo normalizado (AgentInput) junto con la memoria conversacional acumulada
en StateGraph mediante un LLM configurable. Si el modelo decide que se requiere invocar
capacidades externas, genera tool_calls estructurados; en caso contrario, formula una
respuesta directa para resolver la solicitud.
"""

import logging
import time
from datetime import UTC, datetime
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)
from langchain_core.runnables import Runnable

from app.core.config import settings
from app.core.llm import get_chat_model
from app.core.registry import CapabilityRegistry
from app.models.state import (
    AgentExecutionStatus,
    AgentState,
    AuditRecord,
    CognitiveStepRecord,
    IntentModel,
)

logger = logging.getLogger("jg_agente.nodes.reason")


async def _is_simple_greeting_or_chat_llm(model: BaseChatModel, prompt: str) -> bool:
    """Determina mediante el LLM si un estímulo es un saludo/conversación casual o una petición de acción.

    Elimina heurísticas sintácticas fijas en el Core, delegando en la IA la clasificación semántica
    entre 'GREETING' (saludo, cortesía o despedida) y 'ACTION' (comando, consulta operativa, estado o tarea).
    """
    if not prompt or not prompt.strip():
        return True

    # Atajo determinista para fórmulas unívocas de cortesía puras y aisladas (1-2 palabras),
    # evitando latencia innecesaria en saludos elementales evidentes.
    p_clean = (
        prompt.strip()
        .lower()
        .replace("¿", "")
        .replace("?", "")
        .replace("¡", "")
        .replace("!", "")
        .replace(",", " ")
        .replace(".", " ")
    )
    tokens = set(p_clean.split())
    pure_greetings = {
        "hola",
        "saludos",
        "buenos días",
        "buenas tardes",
        "buenas noches",
        "hey",
        "hi",
        "hello",
        "adiós",
        "chao",
        "gracias",
    }
    if tokens and tokens.issubset(pure_greetings):
        return True

    classification_messages: list[BaseMessage] = [
        SystemMessage(
            content=(
                "Eres un clasificador de intenciones para un agente autónomo.\n"
                "Determina si el siguiente mensaje del usuario es:\n"
                "- 'GREETING': si es únicamente un saludo, despedida, agradecimiento o cortesía conversacional básica, sin ninguna solicitud de tarea, acción, comando o información técnica/operativa.\n"
                "- 'ACTION': si contiene cualquier petición, comando, pregunta operativa, consulta de estado, diagnóstico o tarea técnica.\n\n"
                "Responde ÚNICAMENTE con la palabra 'GREETING' o 'ACTION'."
            )
        ),
        HumanMessage(content=prompt),
    ]

    try:
        try:
            res = await model.ainvoke(classification_messages)
        except NotImplementedError:
            res = model.invoke(classification_messages)

        content = str(getattr(res, "content", res)).strip().upper()
        if "ACTION" in content:
            return False
        if "GREETING" in content:
            return True
    except Exception as exc:
        logger.warning(
            "Error al clasificar intención con el LLM: %s. Asumiendo acción operativa.",
            exc,
        )
        return False

    return False


async def reason_node(
    state: AgentState,
    registry: CapabilityRegistry,
    llm: BaseChatModel | None = None,
    system_prompt: str | None = None,
) -> dict[str, Any]:
    """Ejecuta el ciclo de razonamiento del LLM sobre el estado actual del agente.

    Args:
        state: Estado global actual del grafo (AgentState).
        registry: Catálogo de capacidades para enlazar herramientas disponibles.
        llm: Instancia opcional de BaseChatModel (si es None, se resuelve vía get_chat_model()).
        system_prompt: Directriz opcional del sistema (si es None, se utiliza la de configuración).

    Returns:
        Diccionario con las mutaciones parciales de estado para LangGraph (messages, intent, status, audit_trail).
    """
    model = llm or get_chat_model()
    existing_messages = list(state.get("messages") or [])

    # 1. Recuperar el estímulo textual principal
    prompt = ""
    req = state.get("request")
    if req and req.prompt:
        prompt = req.prompt.strip()

    # 2. Reconstrucción y enriquecimiento de la memoria conversacional
    messages_to_send: list[BaseMessage] = []
    has_system = any(isinstance(m, SystemMessage) for m in existing_messages)

    if not has_system:
        sys_content = system_prompt or settings.DEFAULT_SYSTEM_PROMPT
        verbosity = getattr(settings, "AGENT_VERBOSITY", "concise").lower().strip()
        if verbosity == "concise":
            sys_content += (
                "\n\nDIRECTIVAS DE RESPUESTA (CONCISO):\n"
                "- Sé directo, ejecutivo y conciso. Evita introducciones o florituras innecesarias.\n"
                "- Si respondes directamente sin herramientas, proporciona la información esencial en 1 a 3 frases claras.\n"
                "- No hagas meta-comentarios sobre tu propio catálogo interno ni sobre las partes de la pregunta del usuario."
            )
        elif verbosity == "detailed":
            sys_content += (
                "\n\nDIRECTIVAS DE RESPUESTA (DETALLADO):\n"
                "- Proporciona explicaciones minuciosas y detalladas con análisis exhaustivo."
            )
        messages_to_send.append(SystemMessage(content=sys_content))

    messages_to_send.extend(existing_messages)

    # Control determinista de iteración
    eval_records = list(state.get("evaluation_records") or [])
    current_iteration = int(state.get("iteration", 1))
    if eval_records:
        current_iteration += 1

    # Si hay un nuevo prompt en request que no está en el historial, añadirlo
    if prompt:
        has_current_human = (
            len(existing_messages) > 0
            and isinstance(existing_messages[-1], HumanMessage)
            and existing_messages[-1].content == prompt
        )
        if not has_current_human:
            messages_to_send.append(HumanMessage(content=prompt))

    # Si venimos de un ciclo iterativo, inyectar el veredicto del evaluador como contexto guía
    if eval_records:
        last_eval = eval_records[-1]
        guidance_text = (
            f"[Evaluación Semántica Previa (Iteración {current_iteration - 1})]: {last_eval.explanation}\n"
            f"Acción requerida: {last_eval.suggested_next_action or 'Continuar con el objetivo original utilizando las herramientas disponibles.'}"
        )
        messages_to_send.append(HumanMessage(content=guidance_text))

    # 3. Enlace dinámico de herramientas (Tool Binding)
    tools = registry.get_langchain_tools()
    model_to_invoke: Runnable[Any, Any] = model
    if tools and hasattr(model, "bind_tools"):
        try:
            model_to_invoke = model.bind_tools(tools)
        except Exception as exc:
            logger.warning("No se pudieron vincular las herramientas al LLM: %s", exc)

    # 4. Invocación asíncrona del LLM
    start_llm = time.perf_counter()
    try:
        raw_response = await model_to_invoke.ainvoke(messages_to_send)
    except NotImplementedError:
        # Fallback para modelos que solo implementan invoke síncrono
        raw_response = model_to_invoke.invoke(messages_to_send)
    duration_llm_ms = max(0.0, round((time.perf_counter() - start_llm) * 1000.0, 2))

    ai_message: AIMessage
    if isinstance(raw_response, AIMessage):
        ai_message = raw_response
    else:
        ai_message = AIMessage(content=str(getattr(raw_response, "content", raw_response)))
    # 5. Análisis del resultado: ¿tool_calls, plan o respuesta directa?
    has_tool_calls = bool(ai_message.tool_calls)
    planner_engine = registry.get_planner()

    if has_tool_calls:
        tool_names = [tc.get("name") for tc in ai_message.tool_calls]
        tools_str = ", ".join(t for t in tool_names if t)
        logger.info(
            "[reason_node] El modelo generó %d tool call(s): %s",
            len(ai_message.tool_calls),
            tools_str,
        )
        intent = IntentModel(
            goal=prompt or "Ejecución de herramientas operativas",
            action_type="act",
            parameters={"tool_calls": ai_message.tool_calls},
            confidence=1.0,
            reasoning=str(ai_message.content)
            if ai_message.content
            else f"Invocación requerida para: {tools_str}",
        )
        audit_details = {
            "action_type": "act",
            "tool_calls_count": len(ai_message.tool_calls),
            "tools": tool_names,
        }
        step_title = "Razonamiento e Interpretación Cognitiva"
        step_action = f"Selección de Herramienta(s): {tools_str}"
        step_description = f"El agente interpretó la solicitud y determinó la ejecución de las herramientas: {tools_str}."
    elif planner_engine is not None and not await _is_simple_greeting_or_chat_llm(model, prompt):
        logger.info(
            "[reason_node] Solicitud operativa detectada con planificador disponible ('%s')",
            planner_engine.name,
        )
        intent = IntentModel(
            goal=prompt or "Elaboración de plan de ejecución",
            action_type="plan",
            parameters={"planner": planner_engine.name},
            confidence=1.0,
            reasoning=f"Se requiere planificar la ejecución mediante el motor '{planner_engine.name}'.",
        )
        audit_details = {
            "action_type": "plan",
            "planner": planner_engine.name,
        }
        step_title = "Razonamiento y Planificación Cognitiva"
        step_action = f"Delegación a Planificador: {planner_engine.name}"
        step_description = (
            f"Solicitud operativa compleja detectada. El agente delega en el motor '{planner_engine.name}' "
            f"para formular un plan de pasos secuenciales."
        )
    else:
        logger.info(
            "[reason_node] El modelo generó respuesta directa sin herramientas ni planificación"
        )
        intent = IntentModel(
            goal=prompt or "Resolución directa",
            action_type="conclude",
            parameters={"response": ai_message.content},
            confidence=1.0,
            reasoning="Respuesta directa generada por el LLM.",
        )
        audit_details = {
            "action_type": "conclude",
            "response_length": len(str(ai_message.content)),
        }
        step_title = "Razonamiento y Respuesta Directa"
        step_action = "Resolución Conversacional"
        step_description = (
            "El agente analizó la consulta y determinó que no requiere invocar herramientas operativas, "
            "procediendo a responder directamente."
        )

    if current_iteration > 1:
        step_title = f"{step_title} (Iteración {current_iteration})"

    cognitive_step = CognitiveStepRecord(
        step_id=f"cog_reason_{int(time.time() * 1000)}",
        node="reason",
        title=step_title,
        action=step_action,
        description=step_description,
        status="completed",
        details={
            "goal": intent.goal,
            "action_type": intent.action_type,
            "reasoning": intent.reasoning,
            "tool_calls": ai_message.tool_calls if has_tool_calls else [],
            "response_preview": str(ai_message.content)[:300] if ai_message.content else None,
            "iteration": current_iteration,
        },
        duration_ms=duration_llm_ms,
        timestamp=datetime.now(UTC),
    )

    return {
        "status": AgentExecutionStatus.REASONING,
        "intent": intent,
        "iteration": current_iteration,
        "messages": [ai_message],
        "cognitive_steps": [cognitive_step],
        "audit_trail": [
            AuditRecord(
                event_type="reasoning_completed",
                actor="llm_reason_node",
                details=audit_details,
                timestamp=datetime.now(UTC),
            )
        ],
    }
