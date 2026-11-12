# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Cálculo de tiempos de espera y gestión de Rate Limiting (HTTP 429) para LLMs."""

import random
import re
from collections.abc import Callable
from typing import Any

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
