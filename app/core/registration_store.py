# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Almacenamiento persistente y excepciones del proceso de registro de jg_agente."""

import contextlib
import json
import logging
import os
from pathlib import Path

from pydantic import ValidationError

from app.models.registration import AgentCredentials

logger = logging.getLogger("jg_agente.registration.store")


class RegistrationError(Exception):
    """Error base en el proceso de registro del agente con el Dashboard."""

    pass


class RegistrationAuthError(RegistrationError):
    """Error de autenticación: bootstrap token inválido, revocado o expirado (HTTP 401)."""

    pass


class RegistrationConflictError(RegistrationError):
    """Error de conflicto: bootstrap token ya consumido o agente ya registrado (HTTP 409)."""

    pass


class DashboardConnectionError(RegistrationError):
    """Fallo de conectividad o indisponibilidad temporal del Dashboard."""

    pass


class CredentialStore:
    """Gestiona el almacenamiento y carga persistente y segura de credenciales locales."""

    @staticmethod
    def resolve_path(
        path: Path | str | None, default_path: str = ".agent_credentials.json"
    ) -> Path:
        """Resuelve la ruta al archivo de credenciales."""
        return Path(path) if path is not None else Path(default_path)

    @classmethod
    def save(cls, credentials: AgentCredentials, path: Path | str | None = None) -> None:
        """Guarda las credenciales de forma atómica en formato JSON aplicando permisos 0600 en POSIX."""
        target = cls.resolve_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)

        data = credentials.model_dump(mode="json")
        json_content = json.dumps(data, indent=2, ensure_ascii=False)
        tmp_target = target.with_name(f"{target.name}.tmp")

        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        fd = os.open(tmp_target, flags, 0o600)
        opened_file = False
        try:
            if os.name == "posix":
                try:
                    os.fchmod(fd, 0o600)
                except OSError as e:
                    logger.warning(
                        "No se pudieron restringir los permisos a 0600 en descriptor de %s: %s",
                        tmp_target,
                        e,
                    )
            with open(fd, "w", encoding="utf-8", closefd=True) as f:
                opened_file = True
                f.write(json_content)
                f.flush()
                os.fsync(f.fileno())

            os.replace(tmp_target, target)
        except Exception:
            if not opened_file:
                with contextlib.suppress(OSError):
                    os.close(fd)
            if tmp_target.exists():
                with contextlib.suppress(OSError):
                    tmp_target.unlink(missing_ok=True)
            raise

        logger.info("Credenciales del agente guardadas atómicamente en: %s", target)

    @classmethod
    def load(cls, path: Path | str | None = None) -> AgentCredentials | None:
        """Carga las credenciales desde el archivo. Devuelve None si no existe o es corrupto."""
        target = cls.resolve_path(path)
        if not target.is_file():
            return None

        try:
            content = target.read_text(encoding="utf-8").strip()
            if not content:
                return None
            data = json.loads(content)
            return AgentCredentials.model_validate(data)
        except (json.JSONDecodeError, ValidationError, OSError) as e:
            logger.warning(
                "Archivo de credenciales en %s corrupto o inválido: %s",
                target,
                e,
            )
            return None

    @classmethod
    def exists(cls, path: Path | str | None = None) -> bool:
        """Comprueba si el archivo de credenciales existe."""
        return cls.resolve_path(path).is_file()

    @classmethod
    def clear(cls, path: Path | str | None = None) -> None:
        """Elimina el archivo de credenciales si existe."""
        target = cls.resolve_path(path)
        if target.is_file():
            try:
                target.unlink()
                logger.info("Archivo de credenciales eliminado: %s", target)
            except OSError as e:
                logger.error("Error al eliminar credenciales en %s: %s", target, e)
