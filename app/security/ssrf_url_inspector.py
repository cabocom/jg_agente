# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Funciones auxiliares de inspección de URLs, parámetros de herramientas y metadatos DNS Pinning."""

import ipaddress
import logging
import re
from typing import Any
from urllib.parse import urlparse, urlunparse

from app.security.ip_policy import (
    DEFAULT_ALLOWED_SCHEMES,
    DEFAULT_BLOCKED_HOSTNAMES,
)

logger = logging.getLogger("jg_agente.security.ssrf_url_inspector")


def validate_pre_dns(
    validator: Any,
    url: str,
) -> tuple[bool, str | None, Any, str | None, ipaddress.IPv4Address | ipaddress.IPv6Address | None]:
    """Comprobaciones preliminares antes de resolución DNS."""
    if not validator.enforce:
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
            f"Esquema de protocolo no permitido '{scheme}'. Solo se autorizan: {sorted(DEFAULT_ALLOWED_SCHEMES)}",
            parsed,
            None,
            None,
        )

    hostname = parsed.hostname
    if not hostname:
        return False, f"URL sin hostname válido: '{clean_url}'", parsed, None, None

    host_lower = hostname.lower()
    if validator.is_host_allowed_explicitly(host_lower):
        return True, None, parsed, hostname, None

    if host_lower in DEFAULT_BLOCKED_HOSTNAMES:
        return False, f"Hostname '{hostname}' prohibido por política SSRF", parsed, hostname, None

    if any(host_lower.endswith(sfx) for sfx in (".local", ".internal", ".localhost")):
        return (
            False,
            f"Dominio interno '{hostname}' bloqueado por política SSRF",
            parsed,
            hostname,
            None,
        )

    try:
        literal_ip = ipaddress.ip_address(host_lower)
        blocked, reason = validator.is_ip_blocked(literal_ip)
        return (
            (False, reason, parsed, hostname, literal_ip)
            if blocked
            else (True, None, parsed, hostname, literal_ip)
        )
    except ValueError:
        return True, None, parsed, hostname, None


def build_pinned_info(parsed: Any, hostname: str, chosen_ip: str) -> dict[str, Any]:
    """Construye el diccionario de metadatos de conexión fijada (DNS Pinning)."""
    scheme = (parsed.scheme or "http").lower()
    port = parsed.port or (443 if scheme == "https" else 80)
    standard_port = (scheme == "https" and port == 443) or (scheme == "http" and port == 80)
    host_header = hostname if standard_port else f"{hostname}:{port}"

    ip_obj = ipaddress.ip_address(chosen_ip)
    ip_host_str = f"[{chosen_ip}]" if ip_obj.version == 6 else chosen_ip
    netloc = f"{ip_host_str}:{parsed.port}" if parsed.port else ip_host_str
    pinned_url = urlunparse(
        (parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment)
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


def validate_tool_arguments_for_ssrf(
    validator: Any,
    tool_name: str,
    args: dict[str, Any],
    makes_http_requests: bool = False,
) -> tuple[bool, str | None]:
    """Inspecciona los argumentos de una herramienta para detectar intentos SSRF."""
    if not validator.enforce:
        return True, None
    url_regex = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
    for arg_key, arg_val in args.items():
        if not isinstance(arg_val, str):
            continue
        val_str = arg_val.strip()
        for found_url in url_regex.findall(val_str):
            is_safe, reason = validator.validate_url(found_url, resolve_dns=True)
            if not is_safe:
                logger.warning(
                    "Bloqueo SSRF en tool '%s' (arg '%s'): %s", tool_name, arg_key, reason
                )
                return (
                    False,
                    f"Argumento '{arg_key}' contiene URL no autorizada en tool '{tool_name}': {reason}",
                )
        try:
            ip_obj = ipaddress.ip_address(val_str)
            blocked, reason = validator.is_ip_blocked(ip_obj)
            if blocked:
                return (
                    False,
                    f"Argumento '{arg_key}' contiene IP prohibida '{val_str}' en tool '{tool_name}': {reason}",
                )
        except ValueError:
            pass
    return True, None
