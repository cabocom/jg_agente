# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Hook de compatibilidad transparente Cython + Pydantic v2 en contenedor Docker.

Python ejecuta sitecustomize.py automáticamente en cada invocación al arrancar
el intérprete. Registra el tipo cyfunction en Pydantic default_ignored_types
para que los métodos compilados a binarios nativos ELF (.so) sean reconocidos
como métodos legítimos y no como campos de datos sin tipar.
"""

from __future__ import annotations


def _setup_cython_pydantic_compat() -> None:
    try:
        import pydantic._internal._model_construction as mc  # type: ignore[import-not-found]  # pyright: ignore[reportMissingImports]

        try:
            import app._cyprobe as cp

            cy_t = type(cp.probe)
            if cy_t is not type(lambda: None):
                orig_default_ignored = mc.default_ignored_types
                mc.default_ignored_types = lambda: orig_default_ignored() + (cy_t,)
        except Exception:
            pass
    except Exception:
        pass


_setup_cython_pydantic_compat()
