# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Nodo cognitivo troncal de razonamiento (reason) para jg_agente.

Procesa el estímulo normalizado (AgentInput) junto con la memoria conversacional acumulada
en StateGraph mediante un LLM configurable. Si el modelo decide que se requiere invocar
capacidades externas, genera tool_calls estructurados; en caso contrario, formula una
respuesta directa para resolver la solicitud.
"""

import json
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
    ToolCall,
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
from app.models.tools import RiskLevel
from app.prompts import get_prompt_manager

logger = logging.getLogger("jg_agente.nodes.reason")


async def _expand_full_action_plan_with_llm(
    model: BaseChatModel,
    prompt: str,
    initial_tool_calls: list[ToolCall],
    registry: CapabilityRegistry,
    past_executions: list[tuple[Any, dict[str, Any]]] | None = None,
    locale: str = "es",
) -> tuple[list[ToolCall], list[dict[str, Any]]]:
    """Expande mediante el LLM la secuencia completa de etapas del plan antes de pausar en HITL.

    Garantiza que cuando una solicitud involucre acciones mutativas (sujetas a HITL),
    el agente formule el plan completo de principio a fin (etapas de lectura y etapas mutativas)
    para mostrarlo íntegro al operador humano sin esconder mutaciones en iteraciones posteriores.
    """
    if not prompt or not initial_tool_calls:
        return initial_tool_calls, []

    prompt_mgr = get_prompt_manager()
    registered_tools = {t.name: t for t in registry.list_tools()}
    registry_has_mutative = any(
        not getattr(t, "read_only", True) or t.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)
        for t in registered_tools.values()
    )
    if not registry_has_mutative:
        return initial_tool_calls, []

    has_mutative = False
    for tc in initial_tool_calls:
        t_def = registered_tools.get(str(tc.get("name") or ""))
        if t_def and (
            not getattr(t_def, "read_only", True)
            or t_def.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)
        ):
            has_mutative = True
            break

    if not has_mutative:
        p_low = prompt.lower()
        mutative_keywords = prompt_mgr.get_mutative_keywords(locale)
        if not any(kw in p_low for kw in mutative_keywords):
            return initial_tool_calls, []

    tools_spec_lines: list[str] = []
    for t in registry.list_tools():
        is_mut = not getattr(t, "read_only", True) or t.risk_level in (
            RiskLevel.HIGH,
            RiskLevel.CRITICAL,
        )
        tools_spec_lines.append(
            f"- {t.name} [tipo={'MUTATIVA (Riesgo ' + t.risk_level.value.upper() + ')' if is_mut else 'SOLO LECTURA (Riesgo LOW)'}]: {t.description}"
        )
    tools_catalog_text = "\n".join(tools_spec_lines)
    first_call = initial_tool_calls[0]

    sys_content = prompt_mgr.render(
        "hitl_planning",
        locale=locale,
        tools_catalog_text=tools_catalog_text,
    )
    human_content = prompt_mgr.render(
        "hitl_human",
        locale=locale,
        prompt=prompt,
        first_call_json=json.dumps(
            {"name": first_call.get("name"), "args": first_call.get("args")}, ensure_ascii=False
        ),
    )

    planning_messages: list[BaseMessage] = [
        SystemMessage(content=sys_content),
        HumanMessage(content=human_content),
    ]

    try:
        try:
            res = await model.ainvoke(planning_messages)
        except NotImplementedError:
            res = model.invoke(planning_messages)

        raw_text = str(getattr(res, "content", res)).strip()
        if "```" in raw_text:
            for part in raw_text.split("```"):
                part_clean = part.strip()
                if part_clean.startswith("json"):
                    part_clean = part_clean[4:].strip()
                if part_clean.startswith("{") and part_clean.endswith("}"):
                    raw_text = part_clean
                    break

        start_idx = raw_text.find("{")
        end_idx = raw_text.rfind("}")
        if start_idx == -1 or end_idx == -1 or end_idx <= start_idx:
            return initial_tool_calls, []

        parsed = json.loads(raw_text[start_idx : end_idx + 1])
        raw_steps = parsed.get("steps")
        if not isinstance(raw_steps, list) or not raw_steps:
            return initial_tool_calls, []

        expanded_calls: list[ToolCall] = []
        steps_meta: list[dict[str, Any]] = []
        for idx, item in enumerate(raw_steps, start=1):
            if not isinstance(item, dict):
                continue
            t_name = str(item.get("tool_name") or item.get("name") or "").strip()
            if t_name not in registered_tools:
                continue
            t_args = item.get("tool_args") or item.get("args") or {}
            if not isinstance(t_args, dict):
                continue
            if "request_id" not in t_args:
                t_args["request_id"] = f"step_{idx}"
            call_id = f"step_{idx}"
            desc = str(
                item.get("description") or item.get("action") or f"Ejecutar {t_name}"
            ).strip()
            t_def = registered_tools[t_name]
            is_mut = not getattr(t_def, "read_only", True) or t_def.risk_level in (
                RiskLevel.HIGH,
                RiskLevel.CRITICAL,
            )
            expanded_calls.append(
                ToolCall(
                    name=t_name,
                    args=t_args,
                    id=call_id,
                    type="tool_call",
                )
            )
            steps_meta.append(
                {
                    "index": idx,
                    "step_id": call_id,
                    "tool_name": t_name,
                    "tool": t_name,
                    "command": t_args.get("command")
                    or t_args.get("target_url")
                    or t_args.get("url")
                    or t_args.get("target")
                    or "",
                    "action": desc,
                    "description": desc,
                    "risk_level": t_def.risk_level.value.upper(),
                    "mutative": is_mut,
                    "read_only": not is_mut,
                    "reversible": bool(t_def.reversible),
                }
            )

        if expanded_calls and any(m.get("mutative") for m in steps_meta):
            if past_executions:
                filtered_calls: list[ToolCall] = []
                filtered_meta: list[dict[str, Any]] = []
                for tc_item, meta_item in zip(expanded_calls, steps_meta, strict=False):
                    tc_norm = {
                        k: v for k, v in (tc_item.get("args") or {}).items() if k != "request_id"
                    }
                    already_ran = any(
                        p_name == tc_item.get("name")
                        and {k: v for k, v in p_args.items() if k != "request_id"} == tc_norm
                        for p_name, p_args in past_executions
                    )
                    if not already_ran:
                        filtered_calls.append(tc_item)
                        meta_item["index"] = len(filtered_meta) + 1
                        filtered_meta.append(meta_item)
                if filtered_calls:
                    return filtered_calls, filtered_meta
            return expanded_calls, steps_meta
    except Exception as exc:
        logger.warning("No se pudo expandir el plan completo con el LLM: %s", exc)

    return initial_tool_calls, []


async def _is_simple_greeting_or_chat_llm(
    model: BaseChatModel, prompt: str, locale: str = "es"
) -> bool:
    """Determina mediante el LLM si un estímulo es un saludo/conversación casual o una petición de acción.

    Elimina heurísticas sintácticas fijas en el Core, delegando en la IA la clasificación semántica
    entre 'GREETING' (saludo, cortesía o despedida) y 'ACTION' (comando, consulta operativa, estado o tarea).
    """
    if not prompt or not prompt.strip():
        return True

    prompt_mgr = get_prompt_manager()

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
    pure_greetings = prompt_mgr.get_pure_greetings(locale)
    if tokens and tokens.issubset(pure_greetings):
        return True

    sys_content = prompt_mgr.render("intent_classifier", locale=locale)
    classification_messages: list[BaseMessage] = [
        SystemMessage(content=sys_content),
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
    prompt_mgr = get_prompt_manager()

    # 1. Recuperar el estímulo textual principal y resolver locale
    prompt = ""
    req = state.get("request")
    if req and req.prompt:
        prompt = req.prompt.strip()

    req_locale = getattr(req, "locale", None) if req else None

    # Si se cargó un único plugin que declara default_locale, resolverlo
    plugin_default_locale: str | None = None
    try:
        loaded_plugins = registry.list_plugins()
        if len(loaded_plugins) == 1:
            plugin_default_locale = getattr(loaded_plugins[0], "default_locale", None)
    except Exception:
        pass

    locale = prompt_mgr.resolve_locale(
        requested_locale=req_locale,
        plugin_default=plugin_default_locale,
        system_default=getattr(settings, "DEFAULT_LOCALE", "es"),
    )

    # 2. Reconstrucción y enriquecimiento de la memoria conversacional
    messages_to_send: list[BaseMessage] = []
    has_system = any(isinstance(m, SystemMessage) for m in existing_messages)

    if not has_system:
        sys_content = prompt_mgr.get_system_prompt(
            locale=locale,
            verbosity=getattr(settings, "AGENT_VERBOSITY", "concise"),
            base_prompt=system_prompt,
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
        executed_summary = [
            f"{getattr(r, 'tool_name', '')}({(getattr(r, 'tool_args', {}) or {}).get('command') or getattr(r, 'tool_args', {})})"
            for r in (state.get("execution_records") or [])
        ]
        already_done_prefix = {
            "es": "\nOperaciones ya ejecutadas (NO repetir): ",
            "en": "\nOperations already executed (DO NOT repeat): ",
            "fr": "\nOpérations déjà exécutées (NE PAS répéter) : ",
            "de": "\nBereits ausgeführte Operationen (NICHT wiederholen): ",
            "it": "\nOperazioni già eseguite (NON ripetere): ",
        }.get(locale, "\nOperaciones ya ejecutadas (NO repetir): ")
        already_done_note = (
            f"{already_done_prefix}{', '.join(executed_summary)}" if executed_summary else ""
        )
        default_next_action = {
            "es": "Continuar con el objetivo original utilizando las herramientas disponibles con nuevos parámetros.",
            "en": "Continue with original goal using available tools with new parameters.",
            "fr": "Poursuivre l'objectif initial à l'aide des outils disponibles avec de nouveaux paramètres.",
            "de": "Das ursprüngliche Ziel mit den verfügbaren Werkzeugen und neuen Parametern fortsetzen.",
            "it": "Continuare con l'obiettivo originale utilizzando gli strumenti disponibili con nuovi parametri.",
        }.get(
            locale,
            "Continuar con el objetivo original utilizando las herramientas disponibles con nuevos parámetros.",
        )
        guidance_text = prompt_mgr.render(
            "guidance",
            locale=locale,
            iteration=current_iteration - 1,
            explanation=last_eval.explanation,
            suggested_next_action=last_eval.suggested_next_action or default_next_action,
            already_done_note=already_done_note,
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
        # Detectar llamadas con argumentos idénticos a pasos ya ejecutados con éxito en la sesión
        past_executions = [
            (
                getattr(r, "tool_name", None),
                getattr(r, "tool_args", {}) or {},
            )
            for r in (state.get("execution_records") or [])
            if str(getattr(r, "status", "")).lower() in ("completed", "stepstatus.completed")
        ]

        def _normalize_args(d: dict[str, Any]) -> dict[str, Any]:
            return {k: v for k, v in d.items() if k != "request_id"}

        def _is_identical_duplicate(tc: ToolCall) -> bool:
            tc_name = tc.get("name")
            tc_args = _normalize_args(tc.get("args") or {})
            for p_name, p_args in past_executions:
                if p_name == tc_name and _normalize_args(p_args) == tc_args:
                    return True
            return False

        active_tool_calls = [tc for tc in ai_message.tool_calls if not _is_identical_duplicate(tc)]

        if not active_tool_calls and ai_message.tool_calls:
            logger.info(
                "[reason_node] Todas las herramientas invocadas ya fueron ejecutadas con argumentos idénticos. Concluyendo con la información disponible."
            )
            intent = IntentModel(
                goal=prompt or "Resolución con evidencia existente",
                action_type="conclude",
                parameters={
                    "response": ai_message.content
                    or "Operaciones completadas con la evidencia recopilada."
                },
                confidence=1.0,
                reasoning="Las herramientas invocadas ya fueron ejecutadas previamente con idénticos parámetros.",
            )
            audit_details = {
                "action_type": "conclude",
                "deduplicated_calls": len(ai_message.tool_calls),
            }
            step_title, step_action, step_description = prompt_mgr.get_cognitive_meta(
                "conclude_dedup", locale=locale
            )
        else:
            plan_steps_meta: list[dict[str, Any]] = []
            model_cls_name = model.__class__.__name__.lower()
            is_real_llm = (
                "mock" not in model_cls_name
                and "fake" not in model_cls_name
                and settings.LLM_PROVIDER != "mock"
            )
            if is_real_llm and state.get("approval") is None and len(active_tool_calls) == 1:
                expanded_calls, expanded_meta = await _expand_full_action_plan_with_llm(
                    model=model,
                    prompt=prompt,
                    initial_tool_calls=active_tool_calls,
                    registry=registry,
                    past_executions=past_executions,
                    locale=locale,
                )
                if len(expanded_calls) >= 1 and expanded_meta:
                    active_tool_calls = expanded_calls
                    plan_steps_meta = expanded_meta
                    ai_message.tool_calls = active_tool_calls

            tool_names = [tc.get("name") for tc in active_tool_calls]

            def _format_tc_summary(tc: Any) -> str:
                name = str(tc.get("name") or "tool")
                args = tc.get("args") or {}
                if isinstance(args, dict):
                    cmd = (
                        args.get("command")
                        or args.get("target_url")
                        or args.get("url")
                        or args.get("target")
                        or args.get("query")
                    )
                    if cmd:
                        return f"{name} → '{cmd}'"
                return name

            calls_summary = ", ".join(_format_tc_summary(tc) for tc in active_tool_calls)
            logger.info(
                "[reason_node] El modelo generó %d tool call(s) activas: %s",
                len(active_tool_calls),
                calls_summary,
            )
            intent_params: dict[str, Any] = {"tool_calls": active_tool_calls}
            if plan_steps_meta:
                intent_params["plan_steps_metadata"] = plan_steps_meta

            intent = IntentModel(
                goal=prompt or "Ejecución de herramientas operativas",
                action_type="act",
                parameters=intent_params,
                confidence=1.0,
                reasoning=str(ai_message.content)
                if ai_message.content
                else f"Invocación requerida para: {calls_summary}",
            )
            audit_details = {
                "action_type": "act",
                "tool_calls_count": len(active_tool_calls),
                "tools": tool_names,
            }
            step_title, step_action, step_description = prompt_mgr.get_cognitive_meta(
                "act",
                locale=locale,
                count=len(active_tool_calls),
                summary=calls_summary,
            )
    elif planner_engine is not None and not await _is_simple_greeting_or_chat_llm(
        model, prompt, locale=locale
    ):
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
        step_title, step_action, step_description = prompt_mgr.get_cognitive_meta(
            "plan", locale=locale, planner=planner_engine.name
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
        step_title, step_action, step_description = prompt_mgr.get_cognitive_meta(
            "conclude_direct", locale=locale
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
            "locale": locale,
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
