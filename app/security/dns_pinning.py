# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Backends de conexión HTTPCore para mitigación activa de DNS Rebinding y fijado de IP (DNS Pinning)."""

import ipaddress
import logging
from typing import Any

from httpcore import AnyIOBackend, SyncBackend

from app.security.ip_policy import SSRFValidationError
from app.security.ssrf_validator import SSRFValidator, get_ssrf_validator

logger = logging.getLogger("jg_agente.security.dns_pinning")


class SSRFSafeSyncBackend(SyncBackend):
    """Backend sincrónico de red para httpcore con protección SSRF y DNS Pinning a nivel TCP."""

    def __init__(
        self,
        dns_pin_map: dict[str, str] | None = None,
        validator: SSRFValidator | None = None,
    ) -> None:
        super().__init__()
        self.dns_pin_map = dns_pin_map or {}
        self.validator = validator or get_ssrf_validator()

    def _resolve_and_verify_target(self, host: str, port: int) -> str:
        """Determina la IP fijada o resuelve y valida el host sincrónicamente."""
        host_lower = host.lower()
        if host_lower in self.dns_pin_map:
            target_host = self.dns_pin_map[host_lower]
        else:
            is_literal_ip = False
            try:
                ipaddress.ip_address(host)
                is_literal_ip = True
            except ValueError:
                is_literal_ip = False

            if (
                not is_literal_ip
                and self.validator.enforce
                and not self.validator.is_host_allowed_explicitly(host_lower)
            ):
                resolved = self.validator.resolve_host(host, port)
                if not resolved:
                    raise SSRFValidationError(
                        f"No se pudo resolver la dirección para el host '{host}'",
                        target=host,
                    )
                for ip_str in resolved:
                    ip_obj = ipaddress.ip_address(ip_str)
                    blocked, reason = self.validator.is_ip_blocked(ip_obj)
                    if blocked:
                        raise SSRFValidationError(
                            f"Resolución de host '{host}' apunta a IP prohibida {ip_str}: {reason}",
                            target=host,
                        )
                sorted_ips = sorted(resolved, key=lambda x: (":" in x, x))
                target_host = sorted_ips[0]
            else:
                target_host = host

        if self.validator.enforce:
            target_ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address | None = None
            try:
                target_ip_obj = ipaddress.ip_address(target_host)
            except ValueError:
                target_ip_obj = None

            if target_ip_obj is not None:
                blocked, reason = self.validator.is_ip_blocked(target_ip_obj)
                if blocked:
                    raise SSRFValidationError(
                        f"Conexión TCP bloqueada a IP prohibida {target_host}: {reason}",
                        target=target_host,
                    )

        return target_host

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Any = None,
    ) -> Any:
        target_host = self._resolve_and_verify_target(host, port)
        return super().connect_tcp(
            host=target_host,
            port=port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )


class SSRFSafeAsyncBackend(AnyIOBackend):
    """Backend asíncrono de red para httpcore con protección SSRF y DNS Pinning a nivel TCP."""

    def __init__(
        self,
        dns_pin_map: dict[str, str] | None = None,
        validator: SSRFValidator | None = None,
    ) -> None:
        super().__init__()
        self.dns_pin_map = dns_pin_map or {}
        self.validator = validator or get_ssrf_validator()

    async def _resolve_and_verify_target_async(self, host: str, port: int) -> str:
        """Determina la IP fijada o resuelve y valida el host asíncronamente."""
        host_lower = host.lower()
        if host_lower in self.dns_pin_map:
            target_host = self.dns_pin_map[host_lower]
        else:
            is_literal_ip = False
            try:
                ipaddress.ip_address(host)
                is_literal_ip = True
            except ValueError:
                is_literal_ip = False

            if (
                not is_literal_ip
                and self.validator.enforce
                and not self.validator.is_host_allowed_explicitly(host_lower)
            ):
                resolved = await self.validator.resolve_host_async(host, port)
                if not resolved:
                    raise SSRFValidationError(
                        f"No se pudo resolver la dirección para el host '{host}'",
                        target=host,
                    )
                for ip_str in resolved:
                    ip_obj = ipaddress.ip_address(ip_str)
                    blocked, reason = self.validator.is_ip_blocked(ip_obj)
                    if blocked:
                        raise SSRFValidationError(
                            f"Resolución de host '{host}' apunta a IP prohibida {ip_str}: {reason}",
                            target=host,
                        )
                sorted_ips = sorted(resolved, key=lambda x: (":" in x, x))
                target_host = sorted_ips[0]
            else:
                target_host = host

        if self.validator.enforce:
            target_ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address | None = None
            try:
                target_ip_obj = ipaddress.ip_address(target_host)
            except ValueError:
                target_ip_obj = None

            if target_ip_obj is not None:
                blocked, reason = self.validator.is_ip_blocked(target_ip_obj)
                if blocked:
                    raise SSRFValidationError(
                        f"Conexión TCP bloqueada a IP prohibida {target_host}: {reason}",
                        target=target_host,
                    )

        return target_host

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Any = None,
    ) -> Any:
        target_host = await self._resolve_and_verify_target_async(host, port)
        return await super().connect_tcp(
            host=target_host,
            port=port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )
