# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Fábrica de transportes y clientes HTTP seguros contra SSRF y DNS Rebinding."""

import ssl
from typing import Any

import httpcore
import httpx

from app.security.dns_pinning import SSRFSafeAsyncBackend, SSRFSafeSyncBackend
from app.security.ssrf_validator import SSRFValidator, get_ssrf_validator


class SSRFSafeTransport(httpx.HTTPTransport):
    """Transporte HTTP sincrónico para httpx con mitigación activa contra SSRF y DNS Rebinding."""

    def __init__(
        self,
        dns_pin_map: dict[str, str] | None = None,
        validator: SSRFValidator | None = None,
        verify: ssl.SSLContext | str | bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(verify=verify, **kwargs)
        self._dns_pin_map = dns_pin_map or {}
        self._validator = validator or get_ssrf_validator()
        self._pool = httpcore.ConnectionPool(
            ssl_context=getattr(self._pool, "_ssl_context", None),
            max_connections=getattr(self._pool, "_max_connections", 10),
            max_keepalive_connections=getattr(self._pool, "_max_keepalive_connections", None),
            keepalive_expiry=getattr(self._pool, "_keepalive_expiry", None),
            http1=getattr(self._pool, "_http1", True),
            http2=getattr(self._pool, "_http2", False),
            network_backend=SSRFSafeSyncBackend(
                dns_pin_map=self._dns_pin_map,
                validator=self._validator,
            ),
        )


class SSRFSafeAsyncTransport(httpx.AsyncHTTPTransport):
    """Transporte HTTP asíncrono para httpx con mitigación activa contra SSRF y DNS Rebinding."""

    def __init__(
        self,
        dns_pin_map: dict[str, str] | None = None,
        validator: SSRFValidator | None = None,
        verify: ssl.SSLContext | str | bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(verify=verify, **kwargs)
        self._dns_pin_map = dns_pin_map or {}
        self._validator = validator or get_ssrf_validator()
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=getattr(self._pool, "_ssl_context", None),
            max_connections=getattr(self._pool, "_max_connections", 10),
            max_keepalive_connections=getattr(self._pool, "_max_keepalive_connections", None),
            keepalive_expiry=getattr(self._pool, "_keepalive_expiry", None),
            http1=getattr(self._pool, "_http1", True),
            http2=getattr(self._pool, "_http2", False),
            network_backend=SSRFSafeAsyncBackend(
                dns_pin_map=self._dns_pin_map,
                validator=self._validator,
            ),
        )


def create_ssrf_safe_client(
    dns_pin_map: dict[str, str] | None = None,
    validator: SSRFValidator | None = None,
    timeout: float | httpx.Timeout = 10.0,
    verify: ssl.SSLContext | str | bool = True,
    **kwargs: Any,
) -> httpx.Client:
    """Crea un cliente httpx sincrónico seguro contra SSRF y DNS Rebinding."""
    transport = SSRFSafeTransport(
        dns_pin_map=dns_pin_map,
        validator=validator,
        verify=verify,
    )
    return httpx.Client(transport=transport, timeout=timeout, **kwargs)


def create_async_ssrf_safe_client(
    dns_pin_map: dict[str, str] | None = None,
    validator: SSRFValidator | None = None,
    timeout: float | httpx.Timeout = 10.0,
    verify: ssl.SSLContext | str | bool = True,
    **kwargs: Any,
) -> httpx.AsyncClient:
    """Crea un cliente httpx asíncrono seguro contra SSRF y DNS Rebinding."""
    transport = SSRFSafeAsyncTransport(
        dns_pin_map=dns_pin_map,
        validator=validator,
        verify=verify,
    )
    return httpx.AsyncClient(transport=transport, timeout=timeout, **kwargs)
