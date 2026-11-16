# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Tests unitarios para la adaptación y sanitización de voz/telefonía (Asterisk TTS)."""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.models.io import AgentInput, UserContext
from app.models.state import AgentState
from app.nodes.conclude_response_synthesizer import (
    sanitize_for_voice_tts,
    synthesize_final_response,
)
from app.nodes.reason_context import (
    build_reason_messages,
    is_voice_telephony_request,
)


def test_sanitize_for_voice_tts_removes_urls_and_sources() -> None:
    raw_text = (
        "El Real Madrid lidera la clasificación con 65 puntos.\n\n"
        "Consulta más detalles en https://as.com/futbol/clasificacion y [Marca](https://marca.com).\n"
        "Fuente: Diario AS (https://as.com)\n"
        "**Importante**: El *próximo* partido es el sábado."
    )
    cleaned = sanitize_for_voice_tts(raw_text)

    assert "https://" not in cleaned
    assert "as.com" not in cleaned
    assert "Fuente:" not in cleaned
    assert "**" not in cleaned
    assert "*" not in cleaned
    assert "El Real Madrid lidera la clasificación con 65 puntos." in cleaned
    assert "Marca" in cleaned
    assert "Importante: El próximo partido es el sábado." in cleaned


def test_is_voice_telephony_request_detection() -> None:
    # 1. Petición web estándar
    web_req = AgentInput(
        execution_id="exec-1",
        thread_id="thread-1",
        prompt="¿Qué tal?",
        parameters={},
        metadata={"origin": "jg_hub_web_console"},
    )
    assert is_voice_telephony_request({"request": web_req}) is False

    # 2. Petición con is_telephony: True en parameters
    tel_req1 = AgentInput(
        execution_id="exec-2",
        thread_id="thread-2",
        prompt="¿Qué hora es?",
        parameters={"is_telephony": True},
    )
    assert is_voice_telephony_request({"request": tel_req1}) is True

    # 3. Petición Asterisk simulation_type
    tel_req2 = AgentInput(
        execution_id="exec-3",
        thread_id="thread-3",
        prompt="Hola",
        parameters={"simulation_type": "asterisk_voice"},
    )
    assert is_voice_telephony_request({"request": tel_req2}) is True

    # 4. Petición con canal SIP
    tel_req3 = AgentInput(
        execution_id="exec-4",
        thread_id="thread-4",
        prompt="Hola",
        parameters={"channel": "SIP/trunk-01"},
    )
    assert is_voice_telephony_request({"request": tel_req3}) is True

    # 5. Petición con rol caller en user_context
    tel_req4 = AgentInput(
        execution_id="exec-5",
        thread_id="thread-5",
        prompt="Hola",
        user_context=UserContext(user_id="u1", role="caller", permissions=[]),
    )
    assert is_voice_telephony_request({"request": tel_req4}) is True


def test_build_reason_messages_injects_telephony_directive() -> None:
    tel_req = AgentInput(
        execution_id="exec-tel",
        thread_id="thread-tel",
        prompt="¿Cuándo juega el Madrid?",
        parameters={"is_telephony": True},
    )
    state: AgentState = {
        "request": tel_req,
        "messages": [HumanMessage(content="¿Cuándo juega el Madrid?")],
    }

    messages, _ = build_reason_messages(
        state, prompt="¿Cuándo juega el Madrid?", locale="es", system_prompt="Eres un bot."
    )
    sys_msg = next((m for m in messages if isinstance(m, SystemMessage)), None)

    assert sys_msg is not None
    assert "[MODO TELEFONÍA / VOZ TTS ACTIVADO]" in sys_msg.content


def test_synthesize_final_response_distinguishes_web_and_telephony() -> None:
    raw_response = (
        "El Real Madrid juega el domingo a las 21:00 contra el Sevilla. "
        "Fuente: [AS.com](https://as.com/futbol) y https://marca.com"
    )

    # Web state: debe mantener enlaces y fuentes
    web_state: AgentState = {
        "request": AgentInput(
            execution_id="exec-web",
            thread_id="thread-web",
            prompt="¿Cuándo juega?",
            parameters={},
        ),
        "messages": [AIMessage(content=raw_response)],
        "execution_records": [],
        "errors": [],
    }
    web_res = synthesize_final_response(
        state=web_state,
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
    assert "https://as.com/futbol" in web_res
    assert "[AS.com]" in web_res

    # Telephony state: debe limpiar URLs y fuentes
    tel_state: AgentState = {
        "request": AgentInput(
            execution_id="exec-tel",
            thread_id="thread-tel",
            prompt="¿Cuándo juega?",
            parameters={"is_telephony": True},
        ),
        "messages": [AIMessage(content=raw_response)],
        "execution_records": [],
        "errors": [],
    }
    tel_res = synthesize_final_response(
        state=tel_state,
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
    assert "https://" not in tel_res
    assert "[AS.com]" not in tel_res
    assert "Fuente:" not in tel_res
    assert "El Real Madrid juega el domingo a las 21:00 contra el Sevilla." in tel_res
