"""Proveedor y factoría de modelos de lenguaje (LLM) para jg_agente.

Proporciona abstracciones configurables y desacopladas para interactuar con modelos
de lenguaje mediante LangChain BaseChatModel, incluyendo un proveedor Mock determinista
para testing y ejecución local, y un cliente compatible con OpenAI/vLLM/Ollama vía HTTP.
"""

import asyncio
import json
import logging
import random
import re
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

from app.core.config import Settings, settings

logger = logging.getLogger("jg_agente.core.llm")

# Jitter aleatorio (segundos) añadido al backoff de HTTP 429 para evitar thundering herd
RATE_LIMIT_JITTER_MIN_SECONDS = 0.1
RATE_LIMIT_JITTER_MAX_SECONDS = 0.5

_DURATION_FULL_RE = re.compile(r"(?:\d+(?:\.\d+)?(?:ms|h|m|s))+")
_DURATION_TOKEN_RE = re.compile(r"(\d+(?:\.\d+)?)(ms|h|m|s)")
_DURATION_UNIT_SECONDS = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}


def parse_duration_seconds(value: str | None) -> float | None:
    """Convierte cabeceras de espera a segundos.

    Admite números planos en segundos ('2', '0.5') y formatos compuestos de proveedores
    como OpenAI/Groq ('250ms', '2s', '1m30s', '1h2m3.5s'). Devuelve None si no es parseable.
    """
    if value is None:
        return None
    text = value.strip().lower()
    if not text:
        return None
    try:
        return max(float(text), 0.0)
    except ValueError:
        pass
    if not _DURATION_FULL_RE.fullmatch(text):
        return None
    return sum(
        float(num) * _DURATION_UNIT_SECONDS[unit] for num, unit in _DURATION_TOKEN_RE.findall(text)
    )


def compute_rate_limit_wait(
    headers: Any,
    attempt: int,
    jitter: Callable[[float, float], float] = random.uniform,
) -> float:
    """Calcula la espera ante un 429: Retry-After > x-ratelimit-reset-tokens > backoff lineal.

    Siempre suma jitter aleatorio uniforme [0.1, 0.5] s al valor base.
    """
    wait_seconds = 2.5 * (attempt + 1)
    retry_after = parse_duration_seconds(headers.get("retry-after"))
    reset_tokens = parse_duration_seconds(headers.get("x-ratelimit-reset-tokens"))
    if retry_after is not None:
        wait_seconds = max(retry_after, 1.0)
    elif reset_tokens is not None:
        wait_seconds = max(reset_tokens, 0.5)
    return wait_seconds + jitter(RATE_LIMIT_JITTER_MIN_SECONDS, RATE_LIMIT_JITTER_MAX_SECONDS)


# ==========================================================
# 1. MockChatModel para Pruebas y Modo Desconectado
# ==========================================================


class MockChatModel(BaseChatModel):
    """Modelo de chat simulado y determinista para testing y desarrollo local.

    Permite configurar respuestas textuales estáticas o predefinir llamadas a herramientas
    (tool_calls). Si auto_tool_calls=True, detecta si el prompt menciona alguna de las herramientas
    enlazadas e infiere automáticamente la tool_call correspondiente.
    """

    response_content: str = Field(
        default="Esta es una respuesta simulada del agente.",
        description="Contenido del mensaje de respuesta si no hay tool_calls",
    )
    tool_calls_to_return: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Lista explícita de tool_calls a retornar por el modelo",
    )
    bound_tools: list[Any] = Field(
        default_factory=list,
        description="Herramientas vinculadas mediante bind_tools()",
    )
    auto_tool_calls: bool = Field(
        default=True,
        description="Infiere automáticamente tool calls si el prompt coincide con nombres de herramientas vinculadas",
    )

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Callable[..., Any] | BaseTool],
        **kwargs: Any,
    ) -> Runnable[Any, Any]:
        """Vincula herramientas al modelo retornando una instancia clonada."""
        clone = self.model_copy()
        clone.bound_tools = list(tools)
        return clone.bind(**kwargs)

    def _determine_output(self, messages: list[BaseMessage]) -> tuple[str, list[dict[str, Any]]]:
        """Calcula el contenido y tool_calls a generar según los mensajes recibidos."""
        if self.tool_calls_to_return:
            return "", list(self.tool_calls_to_return)

        # Buscar el último mensaje de usuario
        last_human_text = ""
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                last_human_text = str(msg.content).lower()
                break

        # Si es una invocación del clasificador de intenciones (saludo vs acción)
        first_sys = (
            messages[0].content if messages and isinstance(messages[0], SystemMessage) else ""
        )
        if "clasificador de intenciones" in str(first_sys).lower():
            greetings = {
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
                "cómo estás",
                "como estas",
                "qué tal",
                "que tal",
                "capacidades",
                "quién eres",
                "quien eres",
                "qué puedes hacer",
                "que puedes hacer",
            }
            operational_markers = {
                "estado",
                "contenedor",
                "docker",
                "pod",
                "servicio",
                "reinicia",
                "ejecuta",
                "detén",
                "para",
                "mata",
                "log",
                "logs",
                "metric",
                "cpu",
                "memoria",
                "disco",
                "red",
                "despliega",
            }
            has_operational = any(marker in last_human_text for marker in operational_markers)
            is_greeting_or_info = any(g in last_human_text for g in greetings)
            is_simple = is_greeting_or_info and not has_operational
            return ("GREETING", []) if is_simple else ("ACTION", [])

        # Si auto_tool_calls está activo y hay herramientas vinculadas
        if self.auto_tool_calls and self.bound_tools and last_human_text:
            for tool in self.bound_tools:
                tool_name = ""
                if isinstance(tool, BaseTool):
                    tool_name = tool.name
                elif isinstance(tool, dict) and "name" in tool:
                    tool_name = tool["name"]
                elif hasattr(tool, "__name__"):
                    tool_name = tool.__name__

                clean_name = tool_name.lower().replace("_", " ")
                # Comprobar coincidencia léxica o de palabras clave
                if tool_name.lower() in last_human_text or any(
                    word in last_human_text for word in clean_name.split() if len(word) > 3
                ):
                    call_id = f"call_{uuid.uuid4().hex[:8]}"
                    logger.debug("MockChatModel auto-generando tool_call para '%s'", tool_name)
                    return "", [
                        {
                            "id": call_id,
                            "name": tool_name,
                            "args": {"query": last_human_text},
                            "type": "tool_call",
                        }
                    ]

        return self.response_content, []

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        content, tool_calls = self._determine_output(messages)
        ai_msg = AIMessage(content=content, tool_calls=tool_calls)
        return ChatResult(generations=[ChatGeneration(message=ai_msg)])

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return self._generate(messages, stop, run_manager=None, **kwargs)

    @property
    def _llm_type(self) -> str:
        return "mock_chat_model"


# ==========================================================
# 2. Cliente HTTP Genérico Compatible con OpenAI
# ==========================================================


class OpenAICompatibleChatModel(BaseChatModel):
    """Cliente HTTP asíncrono para modelos compatibles con la API de OpenAI (vLLM, Ollama, LiteLLM)."""

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
        formatted: list[dict[str, Any]] = []
        for msg in messages:
            if isinstance(msg, SystemMessage):
                formatted.append({"role": "system", "content": str(msg.content)})
            elif isinstance(msg, HumanMessage):
                formatted.append({"role": "user", "content": str(msg.content)})
            elif isinstance(msg, AIMessage):
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
                formatted.append(entry)
            elif isinstance(msg, ToolMessage):
                formatted.append(
                    {
                        "role": "tool",
                        "tool_call_id": getattr(msg, "tool_call_id", None)
                        or f"call_{uuid.uuid4().hex[:8]}",
                        "content": str(msg.content),
                    }
                )
            else:
                formatted.append({"role": "user", "content": str(msg.content)})
        return formatted

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Invocación asíncrona mediante HTTP POST al endpoint /chat/completions."""
        url = f"{self.base_url.rstrip('/')}/chat/completions"
        headers = {
            "Content-Type": "application/json",
        }
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
        data: dict[str, Any] = {}
        async with httpx.AsyncClient(timeout=60.0) as client:
            for attempt in range(max_retries + 1):
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code == 429 and attempt < max_retries:
                    wait_seconds = compute_rate_limit_wait(resp.headers, attempt)
                    logger.warning(
                        "[LLM] Recibido HTTP 429 (Rate Limit de %s). Reintentando en %.2fs (intento %d/%d)...",
                        self.base_url,
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
                        self.base_url,
                        resp.text,
                        json.dumps(payload),
                    )
                resp.raise_for_status()
                data = resp.json()
                break

        choice = data.get("choices", [{}])[0].get("message", {})
        content = choice.get("content") or ""
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


# ==========================================================
# 3. Factoría de Modelos (get_chat_model)
# ==========================================================


def get_chat_model(
    app_settings: Settings | None = None,
    provider: str | None = None,
    model: str | None = None,
    **kwargs: Any,
) -> BaseChatModel:
    """Factoría centralizada para instanciar el modelo de chat configurado.

    Args:
        app_settings: Configuración activa del sistema (default: settings).
        provider: Sobreescritura opcional del proveedor ('mock', 'openai', 'custom', 'ollama').
        model: Sobreescritura opcional del identificador del modelo.
        kwargs: Parámetros adicionales para el modelo.

    Returns:
        Instancia de BaseChatModel lista para ser utilizada en el grafo.
    """
    cfg = app_settings or settings
    chosen_provider = (provider or cfg.LLM_PROVIDER).lower().strip()
    chosen_model = model or cfg.LLM_MODEL

    if chosen_provider in ("mock", "fake", "test"):
        return MockChatModel(**kwargs)

    if chosen_provider in ("openai", "custom", "ollama", "vllm", "groq", "gemini"):
        default_base_url = "https://api.openai.com/v1"
        if chosen_provider == "ollama":
            default_base_url = "http://localhost:11434/v1"
        elif chosen_provider == "groq":
            default_base_url = "https://api.groq.com/openai/v1"
        elif chosen_provider == "gemini":
            default_base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"

        base_url = cfg.LLM_BASE_URL or default_base_url
        return OpenAICompatibleChatModel(
            model_name=chosen_model,
            api_key=cfg.LLM_API_KEY,
            base_url=base_url,
            temperature=cfg.LLM_TEMPERATURE,
            max_tokens=cfg.LLM_MAX_TOKENS,
            **kwargs,
        )

    logger.warning(
        "Proveedor LLM desconocido '%s'. Se usará MockChatModel por defecto.",
        chosen_provider,
    )
    return MockChatModel(**kwargs)
