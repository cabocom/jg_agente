# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Políticas de red, rangos IP restringidos y excepciones para mitigación SSRF."""

import ipaddress

from jg_sdk.security.ssrf import SSRFValidationError

__all__ = [
    "DEFAULT_ALLOWED_SCHEMES",
    "DEFAULT_BLOCKED_HOSTNAMES",
    "DEFAULT_BLOCKED_NETWORKS",
    "RFC1918_NETWORKS",
    "SSRFValidationError",
]


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

RFC1918_NETWORKS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("fc00::/7"),
)
