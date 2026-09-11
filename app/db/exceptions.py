"""Excepciones de la capa de persistencia y base de datos de jg_agente."""

from typing import Any


class PersistenceError(Exception):
    """Excepción tipada elevada ante fallos en operaciones de persistencia de base de datos."""

    def __init__(self, message: str, original_error: Any = None) -> None:
        super().__init__(message)
        self.original_error = original_error
