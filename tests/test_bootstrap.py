# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez <contacto@javiergalvez.com>
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Smoke tests para validar el bootstrap del entorno jg_agente."""

import sys

from app import __version__


def test_package_metadata() -> None:
    """Verifica que los metadatos del paquete app estén definidos."""
    assert __version__ == "0.1.0"


def test_python_version_supported() -> None:
    """Valida que la versión de Python en ejecución sea >= 3.11."""
    assert sys.version_info >= (3, 11), f"Versión incompatible de Python: {sys.version}"


def test_core_dependencies_importable() -> None:
    """Comprueba que todas las dependencias clave del motor se importen correctamente."""
    import asyncpg
    import fastapi
    import httpx
    import langgraph.graph
    import pydantic
    import sqlalchemy

    assert fastapi.__version__ is not None
    assert pydantic.__version__ is not None
    assert langgraph.graph.StateGraph is not None
    assert sqlalchemy.__version__ is not None
    assert httpx.__version__ is not None
    assert callable(asyncpg.connect)
