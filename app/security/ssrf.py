# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Módulo unificado y fachada pública para validación y mitigación de SSRF."""

import threading

from app.security.dns_pinning import (
    SSRFSafeAsyncBackend,
    SSRFSafeSyncBackend,
)
from app.security.ip_policy import (
    DEFAULT_ALLOWED_SCHEMES,
    DEFAULT_BLOCKED_HOSTNAMES,
    DEFAULT_BLOCKED_NETWORKS,
    RFC1918_NETWORKS,
    SSRFValidationError,
)
from app.security.safe_http_client import (
    SSRFSafeAsyncTransport,
    SSRFSafeTransport,
    create_async_ssrf_safe_client,
    create_ssrf_safe_client,
)
from app.security.ssrf_validator import SSRFValidator

_ssrf_lock = threading.Lock()
_default_ssrf_validator: SSRFValidator | None = None


def get_ssrf_validator() -> SSRFValidator:
    """Factory singleton thread-safe para SSRFValidator."""
    global _default_ssrf_validator
    if _default_ssrf_validator is None:
        with _ssrf_lock:
            if _default_ssrf_validator is None:
                _default_ssrf_validator = SSRFValidator()
    return _default_ssrf_validator


__all__ = [
    "DEFAULT_ALLOWED_SCHEMES",
    "DEFAULT_BLOCKED_HOSTNAMES",
    "DEFAULT_BLOCKED_NETWORKS",
    "RFC1918_NETWORKS",
    "SSRFSafeAsyncBackend",
    "SSRFSafeAsyncTransport",
    "SSRFSafeSyncBackend",
    "SSRFSafeTransport",
    "SSRFValidationError",
    "SSRFValidator",
    "_default_ssrf_validator",
    "_ssrf_lock",
    "create_async_ssrf_safe_client",
    "create_ssrf_safe_client",
    "get_ssrf_validator",
]
