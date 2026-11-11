# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Validador central de destinos de red para prevención de ataques SSRF."""

import asyncio
import ipaddress
import logging
import socket
from collections.abc import Sequence
from typing import Any

from app.core.config import settings
from app.security.ip_policy import (
    DEFAULT_BLOCKED_NETWORKS,
    RFC1918_NETWORKS,
    SSRFValidationError,
)
from app.security.ssrf_url_inspector import (
    build_pinned_info as _build_pinned_info_func,
)
from app.security.ssrf_url_inspector import (
    validate_pre_dns as _validate_pre_dns_func,
)
from app.security.ssrf_url_inspector import (
    validate_tool_arguments_for_ssrf as _validate_tool_args_func,
)

logger = logging.getLogger("jg_agente.security.ssrf_validator")


class SSRFValidator:
    """Validador de destinos de red contra ataques SSRF y bypass de seguridad."""

    def __init__(
        self,
        allowed_hosts: Sequence[str] | None = None,
        allowed_networks: Sequence[str | ipaddress.IPv4Network | ipaddress.IPv6Network]
        | None = None,
        allow_private_networks: bool | None = None,
        enforce: bool | None = None,
    ) -> None:
        raw_hosts = allowed_hosts if allowed_hosts is not None else settings.SSRF_ALLOWED_HOSTS
        self.allowed_hosts: set[str] = {h.lower().strip() for h in raw_hosts if h.strip()}

        raw_nets = (
            allowed_networks if allowed_networks is not None else settings.SSRF_ALLOWED_NETWORKS
        )
        self.allowed_networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
        for net in raw_nets:
            if isinstance(net, (ipaddress.IPv4Network, ipaddress.IPv6Network)):
                self.allowed_networks.append(net)
            elif isinstance(net, str) and net.strip():
                try:
                    self.allowed_networks.append(ipaddress.ip_network(net.strip(), strict=False))
                except ValueError as exc:
                    logger.warning("Rango de red en allowlist no válido '%s': %s", net, exc)

        self.allow_private_networks: bool = (
            allow_private_networks
            if allow_private_networks is not None
            else settings.SSRF_ALLOW_PRIVATE_NETWORKS
        )
        self.enforce: bool = enforce if enforce is not None else settings.SSRF_ENFORCE_PROTECTION

    def is_ip_allowed_explicitly(self, ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
        """Comprueba si una dirección IP se encuentra en los rangos CIDR permitidos."""
        return any(ip in net for net in self.allowed_networks)

    def is_ip_blocked(
        self, ip: ipaddress.IPv4Address | ipaddress.IPv6Address
    ) -> tuple[bool, str | None]:
        """Verifica si una IP está en rangos no autorizados."""
        mapped = getattr(ip, "ipv4_mapped", None)
        if mapped is not None:
            blocked, reason = self.is_ip_blocked(mapped)
            return (True, f"{reason} (IPv4 mapeada en IPv6: {ip})") if blocked else (False, None)

        if self.is_ip_allowed_explicitly(ip):
            return False, None

        for blocked_net in DEFAULT_BLOCKED_NETWORKS:
            if ip in blocked_net:
                if self.allow_private_networks and blocked_net in RFC1918_NETWORKS:
                    continue
                return True, f"IP {ip} bloqueada por pertenecer a rango restringido {blocked_net}"

        return False, None

    def validate_ip(self, ip_str: str) -> tuple[bool, str | None]:
        """Valida una dirección IP representada como texto."""
        if not self.enforce:
            return True, None
        try:
            parsed_ip = ipaddress.ip_address(ip_str.strip())
        except ValueError:
            return False, f"Dirección IP no válida: '{ip_str}'"

        blocked, reason = self.is_ip_blocked(parsed_ip)
        return (False, reason) if blocked else (True, None)

    def is_host_allowed_explicitly(self, hostname: str) -> bool:
        """Verifica si el hostname o un sufijo de dominio está en la allowlist."""
        host_lower = hostname.lower().strip()
        if host_lower in self.allowed_hosts:
            return True
        for allowed in self.allowed_hosts:
            if allowed.startswith(".") and host_lower.endswith(allowed):
                return True
            if allowed.startswith("*.") and host_lower.endswith(allowed[1:]):
                return True
        return False

    def resolve_host(self, hostname: str, port: int = 80) -> set[str]:
        """Resuelve el hostname sincrónicamente devolviendo el conjunto de IPs."""
        addr_info = socket.getaddrinfo(
            hostname, port, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM
        )
        return {str(info[4][0]) for info in addr_info}

    async def resolve_host_async(self, hostname: str, port: int = 80) -> set[str]:
        """Resuelve el hostname asíncronamente sin bloquear el bucle de eventos."""
        loop = asyncio.get_running_loop()
        addr_info = await loop.getaddrinfo(
            hostname, port, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM
        )
        return {str(info[4][0]) for info in addr_info}

    def _validate_pre_dns(
        self, url: str
    ) -> tuple[
        bool, str | None, Any, str | None, ipaddress.IPv4Address | ipaddress.IPv6Address | None
    ]:
        """Comprobaciones preliminares antes de resolución DNS."""
        return _validate_pre_dns_func(self, url)

    def _build_pinned_info(self, parsed: Any, hostname: str, chosen_ip: str) -> dict[str, Any]:
        """Construye el diccionario de metadatos de conexión fijada (DNS Pinning)."""
        return _build_pinned_info_func(parsed, hostname, chosen_ip)

    def _check_resolved_ips(
        self, hostname: str, resolved_ips: set[str]
    ) -> tuple[bool, str | None, list[str]]:
        """Verifica que ninguna IP resuelta pertenezca a un rango bloqueado."""
        if not resolved_ips:
            return False, f"No se pudo resolver la dirección para el host '{hostname}'", []
        valid_ips: list[str] = []
        for ip_str in resolved_ips:
            try:
                resolved_ip = ipaddress.ip_address(ip_str)
                blocked, block_reason = self.is_ip_blocked(resolved_ip)
                if blocked:
                    return (
                        False,
                        f"Host '{hostname}' resolvió a IP prohibida {ip_str}: {block_reason}",
                        [],
                    )
                valid_ips.append(ip_str)
            except ValueError:
                continue
        if not valid_ips:
            return False, f"No se obtuvieron IPs válidas para el host '{hostname}'", []
        valid_ips.sort(key=lambda x: (":" in x, x))
        return True, None, valid_ips

    def validate_url(self, url: str, resolve_dns: bool = True) -> tuple[bool, str | None]:
        """Valida minuciosamente una URL contra ataques SSRF."""
        is_valid, reason, parsed, hostname, literal_ip = self._validate_pre_dns(url)
        if (
            not is_valid
            or not self.enforce
            or literal_ip is not None
            or not resolve_dns
            or not hostname
        ):
            return is_valid, reason
        try:
            scheme = (parsed.scheme or "").lower()
            port = parsed.port or (443 if scheme == "https" else 80)
            resolved = self.resolve_host(hostname, port)
            ok, err_msg, _ = self._check_resolved_ips(hostname, resolved)
            return (False, err_msg) if not ok else (True, None)
        except socket.gaierror as dns_err:
            return False, f"Fallo en resolución DNS para '{hostname}': {dns_err}"

    async def validate_url_async(
        self, url: str, resolve_dns: bool = True
    ) -> tuple[bool, str | None]:
        """Valida asíncronamente una URL contra SSRF."""
        is_valid, reason, parsed, hostname, literal_ip = self._validate_pre_dns(url)
        if (
            not is_valid
            or not self.enforce
            or literal_ip is not None
            or not resolve_dns
            or not hostname
        ):
            return is_valid, reason
        try:
            scheme = (parsed.scheme or "").lower()
            port = parsed.port or (443 if scheme == "https" else 80)
            resolved = await self.resolve_host_async(hostname, port)
            ok, err_msg, _ = self._check_resolved_ips(hostname, resolved)
            return (False, err_msg) if not ok else (True, None)
        except socket.gaierror as dns_err:
            return False, f"Fallo en resolución DNS para '{hostname}': {dns_err}"

    def resolve_and_pin_url(self, url: str) -> tuple[bool, str | None, dict[str, Any] | None]:
        """Valida la URL y fija la IP resultante (DNS Pinning) para mitigar TOCTOU."""
        is_valid, reason, parsed, hostname, literal_ip = self._validate_pre_dns(url)
        if not is_valid or parsed is None or hostname is None:
            return False, reason, None
        if not self.enforce:
            host_str = str(literal_ip) if literal_ip else hostname
            return True, None, self._build_pinned_info(parsed, hostname, host_str)
        if literal_ip is not None:
            return True, None, self._build_pinned_info(parsed, hostname, str(literal_ip))
        try:
            scheme = (parsed.scheme or "").lower()
            port = parsed.port or (443 if scheme == "https" else 80)
            resolved = self.resolve_host(hostname, port)
            ok, err_msg, valid_ips = self._check_resolved_ips(hostname, resolved)
            if not ok:
                return False, err_msg, None
            return True, None, self._build_pinned_info(parsed, hostname, valid_ips[0])
        except socket.gaierror as dns_err:
            return False, f"Fallo en resolución DNS para '{hostname}': {dns_err}", None

    async def resolve_and_pin_url_async(
        self, url: str
    ) -> tuple[bool, str | None, dict[str, Any] | None]:
        """Valida y fija la IP resultante de forma asíncrona para mitigar TOCTOU."""
        is_valid, reason, parsed, hostname, literal_ip = self._validate_pre_dns(url)
        if not is_valid or parsed is None or hostname is None:
            return False, reason, None
        if not self.enforce:
            host_str = str(literal_ip) if literal_ip else hostname
            return True, None, self._build_pinned_info(parsed, hostname, host_str)
        if literal_ip is not None:
            return True, None, self._build_pinned_info(parsed, hostname, str(literal_ip))
        try:
            scheme = (parsed.scheme or "").lower()
            port = parsed.port or (443 if scheme == "https" else 80)
            resolved = await self.resolve_host_async(hostname, port)
            ok, err_msg, valid_ips = self._check_resolved_ips(hostname, resolved)
            if not ok:
                return False, err_msg, None
            return True, None, self._build_pinned_info(parsed, hostname, valid_ips[0])
        except socket.gaierror as dns_err:
            return False, f"Fallo en resolución DNS para '{hostname}': {dns_err}", None

    def is_safe_url(self, url: str, resolve_dns: bool = True) -> bool:
        """Devuelve True si la URL es segura, False en caso contrario."""
        is_safe, _ = self.validate_url(url, resolve_dns=resolve_dns)
        return is_safe

    async def is_safe_url_async(self, url: str, resolve_dns: bool = True) -> bool:
        """Devuelve True si la URL es segura (asíncrono), False en caso contrario."""
        is_safe, _ = await self.validate_url_async(url, resolve_dns=resolve_dns)
        return is_safe

    def assert_safe_url(self, url: str, resolve_dns: bool = True) -> None:
        """Verifica la URL y lanza SSRFValidationError si vulnera la política."""
        is_safe, reason = self.validate_url(url, resolve_dns=resolve_dns)
        if not is_safe:
            raise SSRFValidationError(reason or "Destino no permitido por SSRF", target=url)

    async def assert_safe_url_async(self, url: str, resolve_dns: bool = True) -> None:
        """Verifica la URL (asíncrono) y lanza SSRFValidationError si vulnera la política."""
        is_safe, reason = await self.validate_url_async(url, resolve_dns=resolve_dns)
        if not is_safe:
            raise SSRFValidationError(reason or "Destino no permitido por SSRF", target=url)

    def validate_tool_arguments_for_ssrf(
        self,
        tool_name: str,
        args: dict[str, Any],
        makes_http_requests: bool = False,
    ) -> tuple[bool, str | None]:
        """Inspecciona los argumentos de una herramienta para detectar intentos SSRF."""
        return _validate_tool_args_func(self, tool_name, args, makes_http_requests)


def get_ssrf_validator() -> SSRFValidator:
    """Factory singleton thread-safe para obtener SSRFValidator."""
    from app.security.ssrf import get_ssrf_validator as _get_val

    return _get_val()
