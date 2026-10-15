# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez <contacto@javiergalvez.com>
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Módulo de validación y mitigación de Server-Side Request Forgery (SSRF).

Protege a jg_agente contra accesos no autorizados a servicios internos,
metadatos de nube (ej. 169.254.169.254), interfaces loopback (127.0.0.1) y
redes privadas (RFC 1918 / RFC 4193), con soporte de allowlists por configuración.
"""

import asyncio
import ipaddress
import logging
import re
import socket
import ssl
import threading
from collections.abc import Sequence
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpcore
import httpx
from httpcore._backends.anyio import AnyIOBackend
from httpcore._backends.sync import SyncBackend

from app.core.config import settings

logger = logging.getLogger("jg_agente.security.ssrf")


class SSRFValidationError(ValueError):
    """Excepción lanzada cuando una URL, IP o destino vulnera la política SSRF."""

    def __init__(self, message: str, target: str | None = None) -> None:
        super().__init__(message)
        self.target = target


# Redes IPv4 y IPv6 prohibidas por defecto (Loopback, Link-Local, Metadata, RFC 1918, Multicast, etc.)
DEFAULT_BLOCKED_NETWORKS: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = [
    # IPv4 Loopback
    ipaddress.ip_network("127.0.0.0/8"),
    # IPv4 Link-Local / Cloud Instance Metadata Service (AWS, GCP, Azure, OpenStack)
    ipaddress.ip_network("169.254.0.0/16"),
    # IPv4 Redes Privadas (RFC 1918)
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    # IPv4 Especiales y Reservadas
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),  # Carrier-grade NAT (RFC 6598)
    ipaddress.ip_network("192.0.0.0/24"),  # IETF Protocol Assignments
    ipaddress.ip_network("192.0.2.0/24"),  # TEST-NET-1
    ipaddress.ip_network("198.18.0.0/15"),  # Benchmarking
    ipaddress.ip_network("198.51.100.0/24"),  # TEST-NET-2
    ipaddress.ip_network("203.0.113.0/24"),  # TEST-NET-3
    ipaddress.ip_network("224.0.0.0/4"),  # Multicast
    ipaddress.ip_network("240.0.0.0/4"),  # Reservada
    ipaddress.ip_network("255.255.255.255/32"),  # Broadcast
    # IPv6 Loopback y Unspecified
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("::/128"),
    # IPv6 Link-Local
    ipaddress.ip_network("fe80::/10"),
    # IPv6 Unique Local Address (ULA - RFC 4193)
    ipaddress.ip_network("fc00::/7"),
    # IPv6 Multicast y Documentación
    ipaddress.ip_network("ff00::/8"),
    ipaddress.ip_network("2001:db8::/32"),
]

DEFAULT_BLOCKED_HOSTNAMES: set[str] = {
    "localhost",
    "localhost.localdomain",
    "ip6-localhost",
    "ip6-loopback",
    "metadata.google.internal",
    "metadata",
    "instance-data",
}

DEFAULT_ALLOWED_SCHEMES: set[str] = {"http", "https"}


class SSRFValidator:
    """Validador central de destinos de red para prevención de ataques SSRF.

    Evalúa esquemas de protocolo, nombres de host, resolución DNS e IPs de destino
    frente a listas negras de rangos privados y listas blancas explícitas.
    """

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

    def is_ip_allowed_explicitly(
        self,
        ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
    ) -> bool:
        """Comprueba si una dirección IP se encuentra en los rangos CIDR explícitamente permitidos."""
        return any(ip in net for net in self.allowed_networks)

    def is_ip_blocked(
        self,
        ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
    ) -> tuple[bool, str | None]:
        """Verifica si una IP está en rangos no autorizados (loopback, metadata, RFC 1918).

        Las direcciones IPv4 mapeadas en IPv6 (::ffff:a.b.c.d) se normalizan a su IPv4
        subyacente, evitando bypass de la blocklist (p. ej. ::ffff:169.254.169.254).
        """
        mapped = getattr(ip, "ipv4_mapped", None)
        if mapped is not None:
            blocked, reason = self.is_ip_blocked(mapped)
            if blocked:
                return True, f"{reason} (IPv4 mapeada en IPv6: {ip})"
            return False, None

        if self.is_ip_allowed_explicitly(ip):
            return False, None

        # Si se permiten redes privadas por config, omitir comprobación de RFC 1918 / ULA
        for blocked_net in DEFAULT_BLOCKED_NETWORKS:
            if ip in blocked_net:
                # Comprobación de excepción para redes privadas si allow_private_networks=True
                is_private_rfc1918 = blocked_net in (
                    ipaddress.ip_network("10.0.0.0/8"),
                    ipaddress.ip_network("172.16.0.0/12"),
                    ipaddress.ip_network("192.168.0.0/16"),
                    ipaddress.ip_network("fc00::/7"),
                )
                if self.allow_private_networks and is_private_rfc1918:
                    continue

                return True, (f"IP {ip} bloqueada por pertenecer a rango restringido {blocked_net}")

        return False, None

    def validate_ip(
        self,
        ip_str: str,
    ) -> tuple[bool, str | None]:
        """Valida una dirección IP representada como texto."""
        if not self.enforce:
            return True, None

        try:
            parsed_ip = ipaddress.ip_address(ip_str.strip())
        except ValueError:
            return False, f"Dirección IP no válida: '{ip_str}'"

        blocked, reason = self.is_ip_blocked(parsed_ip)
        if blocked:
            return False, reason

        return True, None

    def is_host_allowed_explicitly(self, hostname: str) -> bool:
        """Verifica si el hostname o un sufijo de dominio está en la allowlist."""
        host_lower = hostname.lower().strip()
        if host_lower in self.allowed_hosts:
            return True

        # Soporte para comodines de dominio (ej. '.cabocom.net')
        for allowed in self.allowed_hosts:
            if allowed.startswith(".") and host_lower.endswith(allowed):
                return True
            if allowed.startswith("*.") and host_lower.endswith(allowed[1:]):
                return True

        return False

    def resolve_host(self, hostname: str, port: int = 80) -> set[str]:
        """Resuelve el hostname de forma sincrónica devolviendo un conjunto de direcciones IP."""
        addr_info = socket.getaddrinfo(
            hostname,
            port,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
        )
        return {str(info[4][0]) for info in addr_info}

    async def resolve_host_async(self, hostname: str, port: int = 80) -> set[str]:
        """Resuelve el hostname de forma asíncrona sin bloquear el bucle de eventos."""
        loop = asyncio.get_running_loop()
        addr_info = await loop.getaddrinfo(
            hostname,
            port,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
        )
        return {str(info[4][0]) for info in addr_info}

    def _validate_pre_dns(
        self, url: str
    ) -> tuple[
        bool, str | None, Any, str | None, ipaddress.IPv4Address | ipaddress.IPv6Address | None
    ]:
        """Comprobaciones preliminares antes de resolución DNS.

        Devuelve (is_valid, reason, parsed_url, hostname, literal_ip).
        """
        if not self.enforce:
            return True, None, None, None, None

        if not url or not isinstance(url, str):
            return False, "URL vacía o de tipo incorrecto", None, None, None

        clean_url = url.strip()
        try:
            parsed = urlparse(clean_url)
        except Exception as exc:
            return False, f"Error parseando URL '{clean_url}': {exc}", None, None, None

        scheme = (parsed.scheme or "").lower()
        if scheme not in DEFAULT_ALLOWED_SCHEMES:
            return (
                False,
                f"Esquema de protocolo no permitido '{scheme}'. "
                f"Solo se autorizan: {sorted(DEFAULT_ALLOWED_SCHEMES)}",
                parsed,
                None,
                None,
            )

        hostname = parsed.hostname
        if not hostname:
            return False, f"URL sin hostname válido: '{clean_url}'", parsed, None, None

        hostname_lower = hostname.lower()

        # Comprobación de allowlist explícita
        if self.is_host_allowed_explicitly(hostname_lower):
            return True, None, parsed, hostname, None

        # Comprobación de nombres de host prohibidos
        if hostname_lower in DEFAULT_BLOCKED_HOSTNAMES:
            return (
                False,
                f"Hostname '{hostname}' prohibido por política SSRF",
                parsed,
                hostname,
                None,
            )

        if (
            hostname_lower.endswith(".local")
            or hostname_lower.endswith(".internal")
            or hostname_lower.endswith(".localhost")
        ):
            return (
                False,
                f"Dominio interno '{hostname}' bloqueado por política SSRF",
                parsed,
                hostname,
                None,
            )

        # Comprobar si el hostname es una dirección IP literal
        try:
            literal_ip = ipaddress.ip_address(hostname_lower)
            blocked, reason = self.is_ip_blocked(literal_ip)
            if blocked:
                return False, reason, parsed, hostname, literal_ip
            return True, None, parsed, hostname, literal_ip
        except ValueError:
            pass

        return True, None, parsed, hostname, None

    def _build_pinned_info(self, parsed: Any, hostname: str, chosen_ip: str) -> dict[str, Any]:
        """Construye el diccionario de metadatos de conexión fijada (DNS Pinning)."""
        scheme = (parsed.scheme or "http").lower()
        port = parsed.port or (443 if scheme == "https" else 80)

        # Cabecera Host con puerto si no es estándar
        standard_port = (scheme == "https" and port == 443) or (scheme == "http" and port == 80)
        host_header = hostname if standard_port else f"{hostname}:{port}"

        # Reconstruir URL usando la IP en lugar del hostname (entre corchetes si es IPv6)
        ip_obj = ipaddress.ip_address(chosen_ip)
        ip_host_str = f"[{chosen_ip}]" if ip_obj.version == 6 else chosen_ip
        netloc = f"{ip_host_str}:{parsed.port}" if parsed.port else ip_host_str
        pinned_url = urlunparse(
            (
                parsed.scheme,
                netloc,
                parsed.path,
                parsed.params,
                parsed.query,
                parsed.fragment,
            )
        )

        return {
            "hostname": hostname,
            "pinned_ip": chosen_ip,
            "port": port,
            "scheme": scheme,
            "pinned_url": pinned_url,
            "host_header": host_header,
            "headers": {"Host": host_header},
            "dns_pin_map": {hostname.lower(): chosen_ip},
        }

    def validate_url(
        self,
        url: str,
        resolve_dns: bool = True,
    ) -> tuple[bool, str | None]:
        """Valida minuciosamente una URL contra ataques SSRF.

        Comprueba esquema, hostname, resolución de nombres a IPs y rangos restringidos.
        """
        is_valid, reason, parsed, hostname, literal_ip = self._validate_pre_dns(url)
        if not is_valid:
            return False, reason
        if not self.enforce or literal_ip is not None or not resolve_dns or not hostname:
            return True, None

        try:
            scheme = (parsed.scheme or "").lower()
            port = parsed.port or (443 if scheme == "https" else 80)
            resolved_ips = self.resolve_host(hostname, port)
            if not resolved_ips:
                return False, f"No se pudo resolver la dirección para el host '{hostname}'"

            for ip_str in resolved_ips:
                try:
                    resolved_ip = ipaddress.ip_address(ip_str)
                    blocked, block_reason = self.is_ip_blocked(resolved_ip)
                    if blocked:
                        return (
                            False,
                            f"Host '{hostname}' resolvió a IP prohibida {ip_str}: {block_reason}",
                        )
                except ValueError:
                    continue
        except socket.gaierror as dns_err:
            return False, f"Fallo en resolución DNS para '{hostname}': {dns_err}"

        return True, None

    async def validate_url_async(
        self,
        url: str,
        resolve_dns: bool = True,
    ) -> tuple[bool, str | None]:
        """Valida asíncronamente una URL contra SSRF sin bloquear el event loop."""
        is_valid, reason, parsed, hostname, literal_ip = self._validate_pre_dns(url)
        if not is_valid:
            return False, reason
        if not self.enforce or literal_ip is not None or not resolve_dns or not hostname:
            return True, None

        try:
            scheme = (parsed.scheme or "").lower()
            port = parsed.port or (443 if scheme == "https" else 80)
            resolved_ips = await self.resolve_host_async(hostname, port)
            if not resolved_ips:
                return False, f"No se pudo resolver la dirección para el host '{hostname}'"

            for ip_str in resolved_ips:
                try:
                    resolved_ip = ipaddress.ip_address(ip_str)
                    blocked, block_reason = self.is_ip_blocked(resolved_ip)
                    if blocked:
                        return (
                            False,
                            f"Host '{hostname}' resolvió a IP prohibida {ip_str}: {block_reason}",
                        )
                except ValueError:
                    continue
        except socket.gaierror as dns_err:
            return False, f"Fallo en resolución DNS para '{hostname}': {dns_err}"

        return True, None

    def resolve_and_pin_url(
        self,
        url: str,
    ) -> tuple[bool, str | None, dict[str, Any] | None]:
        """Valida la URL y fija la IP resultante (DNS Pinning) para mitigar TOCTOU/DNS Rebinding."""
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
            resolved_ips = self.resolve_host(hostname, port)
            if not resolved_ips:
                return False, f"No se pudo resolver la dirección para el host '{hostname}'", None

            valid_ips: list[str] = []
            for ip_str in resolved_ips:
                try:
                    resolved_ip = ipaddress.ip_address(ip_str)
                    blocked, block_reason = self.is_ip_blocked(resolved_ip)
                    if blocked:
                        return (
                            False,
                            f"Host '{hostname}' resolvió a IP prohibida {ip_str}: {block_reason}",
                            None,
                        )
                    valid_ips.append(ip_str)
                except ValueError:
                    continue

            if not valid_ips:
                return False, f"No se obtuvieron IPs válidas para el host '{hostname}'", None

            valid_ips.sort(key=lambda x: (":" in x, x))
            chosen_ip = valid_ips[0]
            return True, None, self._build_pinned_info(parsed, hostname, chosen_ip)

        except socket.gaierror as dns_err:
            return False, f"Fallo en resolución DNS para '{hostname}': {dns_err}", None

    async def resolve_and_pin_url_async(
        self,
        url: str,
    ) -> tuple[bool, str | None, dict[str, Any] | None]:
        """Valida y fija la IP resultante de forma asíncrona para mitigar TOCTOU/DNS Rebinding."""
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
            resolved_ips = await self.resolve_host_async(hostname, port)
            if not resolved_ips:
                return False, f"No se pudo resolver la dirección para el host '{hostname}'", None

            valid_ips: list[str] = []
            for ip_str in resolved_ips:
                try:
                    resolved_ip = ipaddress.ip_address(ip_str)
                    blocked, block_reason = self.is_ip_blocked(resolved_ip)
                    if blocked:
                        return (
                            False,
                            f"Host '{hostname}' resolvió a IP prohibida {ip_str}: {block_reason}",
                            None,
                        )
                    valid_ips.append(ip_str)
                except ValueError:
                    continue

            if not valid_ips:
                return False, f"No se obtuvieron IPs válidas para el host '{hostname}'", None

            valid_ips.sort(key=lambda x: (":" in x, x))
            chosen_ip = valid_ips[0]
            return True, None, self._build_pinned_info(parsed, hostname, chosen_ip)

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
        """Inspecciona los argumentos suministrados a una herramienta para detectar intentos SSRF.

        Si la herramienta declara makes_http_requests=True, escanea los parámetros
        de tipo texto en busca de URLs o IPs prohibidas.
        """
        if not self.enforce:
            return True, None

        url_regex = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)

        for arg_key, arg_val in args.items():
            if isinstance(arg_val, str):
                val_str = arg_val.strip()
                # 1. ¿Es una URL explícita?
                found_urls = url_regex.findall(val_str)
                for found_url in found_urls:
                    is_safe, reason = self.validate_url(found_url, resolve_dns=True)
                    if not is_safe:
                        logger.warning(
                            "Bloqueo SSRF en tool '%s' (arg '%s'): %s",
                            tool_name,
                            arg_key,
                            reason,
                        )
                        return False, (
                            f"Argumento '{arg_key}' contiene URL no autorizada en tool "
                            f"'{tool_name}': {reason}"
                        )

                # 2. Si es una IP literal aislada
                try:
                    ip_obj = ipaddress.ip_address(val_str)
                    blocked, reason = self.is_ip_blocked(ip_obj)
                    if blocked:
                        return False, (
                            f"Argumento '{arg_key}' contiene IP prohibida '{val_str}' "
                            f"en tool '{tool_name}': {reason}"
                        )
                except ValueError:
                    pass

        return True, None


# Instancia singleton por defecto y cerrojo de concurrencia
_ssrf_lock = threading.Lock()
_default_ssrf_validator: SSRFValidator | None = None


def get_ssrf_validator() -> SSRFValidator:
    """Factory singleton thread-safe para obtener SSRFValidator."""
    global _default_ssrf_validator
    if _default_ssrf_validator is None:
        with _ssrf_lock:
            if _default_ssrf_validator is None:
                _default_ssrf_validator = SSRFValidator()
    return _default_ssrf_validator


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

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Any = None,
    ) -> Any:
        target_host = host
        host_lower = host.lower()

        # 1. Resolver o fijar IP
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

        # 2. Verificación estricta de la IP final de destino
        if self.validator.enforce:
            target_ip_obj = None
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

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Any = None,
    ) -> Any:
        target_host = host
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

        if self.validator.enforce:
            target_ip_obj = None
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

        return await super().connect_tcp(
            host=target_host,
            port=port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )


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
