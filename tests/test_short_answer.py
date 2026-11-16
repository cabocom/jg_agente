# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Tests unitarios para la modalidad de respuesta corta y concisa (short_answer)."""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.models.io import AgentInput
from app.models.state import AgentState
from app.nodes.conclude_response_synthesizer import (
    sanitize_for_short_answer,
    synthesize_final_response,
)
from app.nodes.reason_context import (
    build_reason_messages,
    is_short_answer_request,
)


def test_sanitize_for_short_answer_removes_urls_and_sources() -> None:
    raw_text = (
        "El Real Madrid lidera la clasificación con 65 puntos.\n\n"
        "Consulta más detalles en https://as.com/futbol/clasificacion y [Marca](https://marca.com).\n"
        "Fuente: Diario AS (https://as.com)\n"
        "**Importante**: El *próximo* partido es el sábado."
    )
    cleaned = sanitize_for_short_answer(raw_text)

    assert "https://" not in cleaned
    assert "as.com" not in cleaned
    assert "Fuente:" not in cleaned
    assert "**" not in cleaned
    assert "*" not in cleaned
    assert "El Real Madrid lidera la clasificación con 65 puntos." in cleaned
    assert "Marca" in cleaned
    assert "Importante: El próximo partido es el sábado." in cleaned


def test_is_short_answer_request_detection() -> None:
    # 1. Petición web estándar
    web_req = AgentInput(
        execution_id="exec-1",
        thread_id="thread-1",
        prompt="¿Qué tal?",
        parameters={},
        metadata={"origin": "jg_hub_web_console"},
    )
    assert is_short_answer_request({"request": web_req}) is False

    # 2. Petición con short_answer: True en parameters
    short_req1 = AgentInput(
        execution_id="exec-2",
        thread_id="thread-2",
        prompt="¿Qué hora es?",
        parameters={"short_answer": True},
    )
    assert is_short_answer_request({"request": short_req1}) is True

    # 3. Petición con verbosity: short
    short_req2 = AgentInput(
        execution_id="exec-3",
        thread_id="thread-3",
        prompt="Hola",
        parameters={"verbosity": "short"},
    )
    assert is_short_answer_request({"request": short_req2}) is True

    # 4. Compatibilidad con canales telefónicos / SIP
    short_req3 = AgentInput(
        execution_id="exec-4",
        thread_id="thread-4",
        prompt="Hola",
        parameters={"channel": "SIP/trunk-01"},
    )
    assert is_short_answer_request({"request": short_req3}) is True


def test_build_reason_messages_injects_short_answer_directive() -> None:
    req = AgentInput(
        execution_id="exec-short",
        thread_id="thread-short",
        prompt="¿Cuándo juega el Madrid?",
        parameters={"short_answer": True},
    )
    state: AgentState = {
        "request": req,
        "messages": [HumanMessage(content="¿Cuándo juega el Madrid?")],
    }

    messages, _ = build_reason_messages(
        state, prompt="¿Cuándo juega el Madrid?", locale="es", system_prompt="Eres un bot."
    )
    sys_msg = next((m for m in messages if isinstance(m, SystemMessage)), None)

    assert sys_msg is not None
    assert "[MODO RESPUESTA CORTA / SHORT ANSWER ACTIVADO]" in sys_msg.content


def test_synthesize_final_response_distinguishes_standard_and_short_answer() -> None:
    raw_response = (
        "El Real Madrid juega el domingo a las 21:00 contra el Sevilla. "
        "Fuente: [AS.com](https://as.com/futbol) y https://marca.com"
    )

    # Standard state: mantiene fuentes y enlaces
    std_state: AgentState = {
        "request": AgentInput(
            execution_id="exec-std",
            thread_id="thread-std",
            prompt="¿Cuándo juega?",
            parameters={},
        ),
        "messages": [AIMessage(content=raw_response)],
        "execution_records": [],
        "errors": [],
    }
    std_res = synthesize_final_response(
        state=std_state,
        is_cancelled=False,
        is_rejected=False,
        is_failed=False,
        is_resolved=True,
        is_iteration_limit_reached=False,
        records=[],
        errors=[],
        last_eval=None,
        approval_val=None,
        max_iterations=5,
    )
    assert "https://as.com/futbol" in std_res
    assert "[AS.com]" in std_res

    # Short answer state: limpia URLs y fuentes
    short_state: AgentState = {
        "request": AgentInput(
            execution_id="exec-short",
            thread_id="thread-short",
            prompt="¿Cuándo juega?",
            parameters={"short_answer": True},
        ),
        "messages": [AIMessage(content=raw_response)],
        "execution_records": [],
        "errors": [],
    }
    short_res = synthesize_final_response(
        state=short_state,
        is_cancelled=False,
        is_rejected=False,
        is_failed=False,
        is_resolved=True,
        is_iteration_limit_reached=False,
        records=[],
        errors=[],
        last_eval=None,
        approval_val=None,
        max_iterations=5,
    )
    assert "https://" not in short_res
    assert "[AS.com]" not in short_res
    assert "Fuente:" not in short_res
    assert "El Real Madrid juega el domingo a las 21:00 contra el Sevilla." in short_res
