# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Sanitización de argumentos, prevención de inyección shell y confinamiento en Workspace Jail."""

import os
import re
import urllib.parse
from pathlib import Path
from typing import Any

# Metacaracteres y secuencias sospechosas de inyección de comandos shell
SHELL_INJECTION_PATTERN = re.compile(r"[;&$`\n\r><|\\'\"]")
# Variante para URLs HTTP/HTTPS donde '&' y comillas son válidos en query strings
URL_SHELL_INJECTION_PATTERN = re.compile(r"[;`$\n\r><|\\]")

# Directorios del sistema de archivos protegidos (base POSIX + rutas canónicas)
_BASE_PROTECTED_SYSTEM_PATHS = (
    "/etc",
    "/boot",
    "/root",
    "/var/root",
    "/sys",
    "/proc",
    "/dev",
    "/usr",
    "/bin",
    "/sbin",
    "/lib",
    "/lib64",
    "/var/run",
    "/run",
    "/private/etc",
    "/private/var/run",
    "/private/var/root",
)


def build_protected_paths() -> tuple[str, ...]:
    """Resuelve dinámicamente las rutas protegidas a sus equivalentes canónicos."""
    paths: set[str] = set(_BASE_PROTECTED_SYSTEM_PATHS)
    for p in _BASE_PROTECTED_SYSTEM_PATHS:
        try:
            resolved = os.path.realpath(p)
            paths.add(resolved)
        except Exception:
            pass
    return tuple(sorted(paths))


PROTECTED_SYSTEM_PATHS = build_protected_paths()


def check_directory_traversal_or_protected_path(arg_val: str) -> tuple[bool, str]:
    """Evalúa si una cadena intenta directory traversal o acceso a rutas protegidas."""
    if not isinstance(arg_val, str) or not arg_val.strip():
        return False, ""

    val = arg_val.strip()
    if val.startswith(("http://", "https://")):
        return False, ""

    decoded_val = urllib.parse.unquote(val)
    clean_val = decoded_val.replace("\\", "/")
    candidates: list[str] = []

    if clean_val.startswith("/"):
        norm = os.path.normpath(clean_val)
        candidates.append(norm)
        try:
            candidates.append(os.path.realpath(clean_val))
            candidates.append(os.path.realpath(norm))
        except Exception:
            pass
    elif ".." in clean_val:
        norm_from_root = os.path.normpath(os.path.join("/", clean_val.lstrip("/")))
        candidates.append(norm_from_root)
        try:
            abs_p = os.path.abspath(clean_val)
            candidates.append(abs_p)
            candidates.append(os.path.realpath(abs_p))
            candidates.append(os.path.realpath(norm_from_root))
        except Exception:
            pass
    elif clean_val.startswith("~"):
        try:
            expanded = os.path.expanduser(clean_val)
            candidates.append(expanded)
            candidates.append(os.path.realpath(expanded))
        except Exception:
            pass

    for cand in candidates:
        for sys_path in PROTECTED_SYSTEM_PATHS:
            if cand == sys_path or cand.startswith(sys_path + "/"):
                return True, cand

    return False, ""


def check_workspace_escape(arg_val: str, workspace_base: str) -> tuple[bool, str]:
    """Comprueba si un argumento tipo ruta escapa del Workspace Jail configurado."""
    if not isinstance(arg_val, str) or not arg_val.strip():
        return False, ""

    val = arg_val.strip()
    if val.startswith(("http://", "https://")):
        return False, ""

    clean_val = urllib.parse.unquote(val).replace("\\", "/")
    is_path_like = "/" in clean_val or ".." in clean_val or clean_val.startswith("~")
    if not is_path_like:
        return False, ""

    base = Path(os.path.realpath(workspace_base))
    if clean_val.startswith("~"):
        candidate = Path(os.path.expanduser(clean_val))
    elif clean_val.startswith("/"):
        candidate = Path(clean_val)
    else:
        candidate = base / clean_val

    resolved = Path(os.path.realpath(candidate))
    if resolved.is_relative_to(base):
        return False, ""
    return True, str(resolved)


def extract_string_arguments(args: Any, parent_key: str = "") -> list[tuple[str, str]]:
    """Extrae recursivamente todas las tuplas (clave_completa, valor_str) de los argumentos."""
    result: list[tuple[str, str]] = []
    if isinstance(args, dict):
        for k, v in args.items():
            full_key = f"{parent_key}.{k}" if parent_key else str(k)
            result.extend(extract_string_arguments(v, full_key))
    elif isinstance(args, list | tuple | set):
        for idx, item in enumerate(args):
            full_key = f"{parent_key}[{idx}]"
            result.extend(extract_string_arguments(item, full_key))
    elif isinstance(args, str):
        result.append((parent_key, args))
    return result


def sanitize_arguments(tool_args: dict[str, Any]) -> dict[str, Any]:
    """Sanitiza y normaliza argumentos de entrada para herramientas."""
    sanitized: dict[str, Any] = {}
    for key, value in tool_args.items():
        if isinstance(value, str):
            sanitized[key] = value.replace("\x00", "").strip()
        elif isinstance(value, dict):
            sanitized[key] = sanitize_arguments(value)
        elif isinstance(value, list):
            sanitized[key] = [
                v.replace("\x00", "").strip() if isinstance(v, str) else v for v in value
            ]
        else:
            sanitized[key] = value
    return sanitized


def check_argument_security_violations(
    tool_args: dict[str, Any],
    jail_base: str | None = None,
) -> tuple[bool, str]:
    """Examina todos los argumentos recursivamente contra inyecciones shell, traversal y escape de jail."""
    for arg_key, arg_val in extract_string_arguments(tool_args):
        if jail_base:
            escapes, resolved_path = check_workspace_escape(arg_val, jail_base)
            if escapes:
                return True, (
                    f"Violación de seguridad: Workspace Jail. La ruta '{arg_val}' "
                    f"(resuelta a '{resolved_path}') escapa del workspace confinado en argumento '{arg_key}'"
                )

        is_blocked_path, matched_path = check_directory_traversal_or_protected_path(arg_val)
        if is_blocked_path:
            return True, (
                f"Violación de seguridad: Acceso denegado a ruta de sistema protegida '{arg_val}' "
                f"(resuelta a '{matched_path}') en argumento '{arg_key}'"
            )

        is_url = arg_val.startswith(("http://", "https://"))
        pattern = URL_SHELL_INJECTION_PATTERN if is_url else SHELL_INJECTION_PATTERN
        if pattern.search(arg_val):
            return True, (
                f"Violación de seguridad: Caracteres sospechosos de inyección shell detectados "
                f"en argumento '{arg_key}': '{arg_val}'"
            )

    return False, ""
