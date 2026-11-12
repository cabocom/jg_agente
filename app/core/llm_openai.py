# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Cliente HTTP compatible con OpenAI (vLLM, Ollama, LiteLLM, Groq, Gemini)."""

import asyncio
import json
import logging
import uuid
from collections.abc import Callable, Sequence
from typing import Any

import httpx
from langchain_core.callbacks.manager import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from pydantic import Field

from app.core.llm_ratelimit import compute_rate_limit_wait

logger = logging.getLogger("jg_agente.core.llm.openai")


def _format_single_message(msg: BaseMessage) -> dict[str, Any]:
    """Convierte un único BaseMessage a formato de rol compatible con OpenAI."""
    if isinstance(msg, SystemMessage):
        return {"role": "system", "content": str(msg.content)}
    if isinstance(msg, HumanMessage):
        return {"role": "user", "content": str(msg.content)}
    if isinstance(msg, AIMessage):
        entry: dict[str, Any] = {
            "role": "assistant",
            "content": str(msg.content) if msg.content is not None else "",
        }
        if msg.tool_calls:
            entry["tool_calls"] = [
                {
                    "id": tc.get("id", f"call_{uuid.uuid4().hex[:8]}"),
                    "type": "function",
                    "function": {
                        "name": tc.get("name"),
                        "arguments": tc.get("args")
                        if isinstance(tc.get("args"), str)
                        else json.dumps(tc.get("args") or {}),
                    },
                }
                for tc in msg.tool_calls
            ]
        return entry
    if isinstance(msg, ToolMessage):
        return {
            "role": "tool",
            "tool_call_id": getattr(msg, "tool_call_id", None) or f"call_{uuid.uuid4().hex[:8]}",
            "content": str(msg.content),
        }
    return {"role": "user", "content": str(msg.content)}


def _extract_tool_calls_from_choice(choice: dict[str, Any]) -> list[dict[str, Any]]:
    """Parsea las llamadas a herramientas retornadas en un mensaje OpenAI."""
    tool_calls: list[dict[str, Any]] = []
    for tc in choice.get("tool_calls", []):
        fn = tc.get("function", {})
        raw_args = fn.get("arguments", {})
        parsed_args: dict[str, Any] = {}
        if isinstance(raw_args, str):
            try:
                val = json.loads(raw_args)
                parsed_args = val if isinstance(val, dict) else {"input": val}
            except Exception:
                parsed_args = {"input": raw_args}
        elif isinstance(raw_args, dict):
            parsed_args = raw_args

        tool_calls.append(
            {
                "id": tc.get("id"),
                "name": fn.get("name"),
                "args": parsed_args,
                "type": "tool_call",
            }
        )
    return tool_calls


async def _post_chat_completions_with_retry(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    base_url: str,
    max_retries: int = 3,
) -> dict[str, Any]:
    """Envía la petición HTTP a la API de OpenAI con reintentos y backoff para 429."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        for attempt in range(max_retries + 1):
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code == 429 and attempt < max_retries:
                wait_seconds = compute_rate_limit_wait(resp.headers, attempt)
                logger.warning(
                    "[LLM] Recibido HTTP 429 (Rate Limit de %s). Reintentando en %.2fs (intento %d/%d)...",
                    base_url,
                    wait_seconds,
                    attempt + 1,
                    max_retries,
                )
                await asyncio.sleep(wait_seconds)
                continue
            if resp.status_code >= 400:
                logger.error(
                    "[LLM] Error %d de %s: %s | Payload: %s",
                    resp.status_code,
                    base_url,
                    resp.text,
                    json.dumps(payload),
                )
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
            return data
    return {}


class OpenAICompatibleChatModel(BaseChatModel):
    """Cliente HTTP asíncrono para modelos compatibles con la API de OpenAI."""

    model_name: str = Field(default="gpt-4o-mini")
    api_key: str | None = Field(default=None)
    base_url: str = Field(default="https://api.openai.com/v1")
    temperature: float = Field(default=0.0)
    max_tokens: int = Field(default=2048)
    bound_tools: list[Any] = Field(default_factory=list)

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Callable[..., Any] | BaseTool],
        **kwargs: Any,
    ) -> Runnable[Any, Any]:
        """Vincula herramientas en formato función de OpenAI."""
        clone = self.model_copy()
        clone.bound_tools = list(tools)
        return clone.bind(**kwargs)

    def _format_tools_for_payload(self) -> list[dict[str, Any]]:
        """Convierte las herramientas vinculadas a especificaciones compatibles de OpenAI."""
        payload_tools: list[dict[str, Any]] = []
        for t in self.bound_tools:
            if isinstance(t, BaseTool):
                schema: dict[str, Any] = {"type": "object", "properties": {}}
                if t.args_schema:
                    raw_schema: Any = None
                    if hasattr(t.args_schema, "model_json_schema") and callable(
                        t.args_schema.model_json_schema
                    ):
                        raw_schema = t.args_schema.model_json_schema()
                    elif hasattr(t.args_schema, "schema") and callable(t.args_schema.schema):
                        raw_schema = t.args_schema.schema()
                    elif isinstance(t.args_schema, dict):
                        raw_schema = t.args_schema

                    if isinstance(raw_schema, dict):
                        schema = {str(k): v for k, v in raw_schema.items()}

                payload_tools.append(
                    {
                        "type": "function",
                        "function": {
                            "name": t.name,
                            "description": t.description,
                            "parameters": schema,
                        },
                    }
                )
            elif isinstance(t, dict):
                payload_tools.append(t)
        return payload_tools

    def _format_messages_for_payload(self, messages: list[BaseMessage]) -> list[dict[str, Any]]:
        """Convierte objetos BaseMessage a diccionarios de roles compatibles con OpenAI."""
        return [_format_single_message(msg) for msg in messages]

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Invocación asíncrona mediante HTTP POST al endpoint /chat/completions."""
        url = f"{self.base_url.rstrip('/')}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": self._format_messages_for_payload(messages),
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        tools = self._format_tools_for_payload()
        if tools:
            payload["tools"] = tools

        max_retries = 3
        data = await _post_chat_completions_with_retry(
            url, headers, payload, self.base_url, max_retries
        )

        choice = data.get("choices", [{}])[0].get("message", {})
        content = choice.get("content") or ""
        tool_calls = _extract_tool_calls_from_choice(choice)
        ai_msg = AIMessage(content=content, tool_calls=tool_calls)
        return ChatResult(generations=[ChatGeneration(message=ai_msg)])

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Invocación síncrona delegando en _agenerate de forma segura."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                return executor.submit(
                    asyncio.run, self._agenerate(messages, stop=stop, **kwargs)
                ).result()

        return asyncio.run(self._agenerate(messages, stop=stop, **kwargs))

    @property
    def _llm_type(self) -> str:
        return "openai_compatible_chat_model"
