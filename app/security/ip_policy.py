# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Políticas de red, rangos IP restringidos y excepciones para mitigación SSRF.

Re-exporta la configuración canónica desde jg_sdk.security.ssrf garantizando
paridad estricta y principio DRY en todo el ecosistema.
"""

from jg_sdk.security.ssrf import (
    DEFAULT_ALLOWED_SCHEMES,
    DEFAULT_BLOCKED_HOSTNAMES,
    DEFAULT_BLOCKED_NETWORKS,
    RFC1918_NETWORKS,
    SSRFValidationError,
)

__all__ = [
    "DEFAULT_ALLOWED_SCHEMES",
    "DEFAULT_BLOCKED_HOSTNAMES",
    "DEFAULT_BLOCKED_NETWORKS",
    "RFC1918_NETWORKS",
    "SSRFValidationError",
]
