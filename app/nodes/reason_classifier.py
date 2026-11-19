# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Clasificación semántica de estímulos de entrada mediante LLM."""

import logging

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from app.core.llm import MockChatModel
from app.prompts import get_prompt_manager

logger = logging.getLogger("jg_agente.nodes.reason_classifier")


def _is_isolated_pure_greeting(prompt: str, locale: str) -> bool:
    """Atajo determinista para fórmulas unívocas de cortesía puras y aisladas."""
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
    prompt_mgr = get_prompt_manager()
    pure_greetings = prompt_mgr.get_pure_greetings(locale)
    return bool(tokens and tokens.issubset(pure_greetings))


async def is_simple_greeting_or_chat_llm(
    model: BaseChatModel, prompt: str, locale: str = "es"
) -> bool:
    """Determina mediante el LLM si un estímulo es un saludo/conversación casual o una petición de acción."""
    if not prompt or not prompt.strip():
        return True

    if isinstance(model, MockChatModel) and _is_isolated_pure_greeting(prompt, locale):
        return True

    prompt_mgr = get_prompt_manager()
    sys_content = prompt_mgr.render("intent_classifier", locale=locale)
    classification_messages: list[BaseMessage] = [
        SystemMessage(content=sys_content),
        HumanMessage(content=prompt),
    ]

    try:
        res = await model.ainvoke(classification_messages)
    except NotImplementedError:
        res = model.invoke(classification_messages)

    content = str(getattr(res, "content", res)).strip().upper()
    if "ACTION" in content:
        return False
    return "GREETING" in content
