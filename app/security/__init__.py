# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Módulo de seguridad de ejecución de jg_agente."""

from app.security.audit import SecurityAuditLogger, get_audit_logger, get_security_audit_logger
from app.security.auth import (
    compute_body_sha256,
    compute_canonical_string,
    compute_hmac_signature,
    verify_control_plane_auth,
    verify_hmac_signature,
)
from app.security.guard import SecurityGuard, get_security_guard
from app.security.ssrf import (
    SSRFSafeAsyncTransport,
    SSRFSafeTransport,
    SSRFValidationError,
    SSRFValidator,
    create_async_ssrf_safe_client,
    create_ssrf_safe_client,
    get_ssrf_validator,
)

__all__ = [
    "SSRFSafeAsyncTransport",
    "SSRFSafeTransport",
    "SSRFValidationError",
    "SSRFValidator",
    "SecurityAuditLogger",
    "SecurityGuard",
    "compute_body_sha256",
    "compute_canonical_string",
    "compute_hmac_signature",
    "create_async_ssrf_safe_client",
    "create_ssrf_safe_client",
    "get_audit_logger",
    "get_security_audit_logger",
    "get_security_guard",
    "get_ssrf_validator",
    "verify_control_plane_auth",
    "verify_hmac_signature",
]
