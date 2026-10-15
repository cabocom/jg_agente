# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Pruebas unitarias para validar el desacoplamiento de sesiones de BD y prevención de saturación de pool."""

from fastapi.routing import APIRoute

from app.api.executions import router as executions_router
from app.db.session import get_async_session


def test_execution_endpoints_do_not_inject_long_running_db_session() -> None:
    """Verifica que ningún endpoint de ejecución o resolución de grafos inyecte get_async_session.

    Evita la retención innecesaria de conexiones del pool durante la ejecución cognitiva
    de grafos LangGraph (AGENTE-STATE-03).
    """
    monitored_paths = [
        ("/executions/trigger", "POST"),
        ("/executions/{thread_id}/approve", "POST"),
        ("/executions/{thread_id}/reject", "POST"),
        ("/executions/approve", "POST"),
        ("/executions/reject", "POST"),
    ]

    routes_found = 0

    for route in executions_router.routes:
        if not isinstance(route, APIRoute):
            continue

        for path, method in monitored_paths:
            if route.path == path and route.methods is not None and method in route.methods:
                routes_found += 1
                # Inspeccionar todos los sub-dependientes de la ruta FastAPI
                all_dependencies = [d.call for d in route.dependant.dependencies]
                assert get_async_session not in all_dependencies, (
                    f"El endpoint {method} {path} no debe inyectar get_async_session para evitar saturación del pool."
                )

    assert routes_found == len(monitored_paths), (
        f"Se esperaban encontrar {len(monitored_paths)} rutas y se encontraron {routes_found}."
    )


def test_quick_read_endpoint_maintains_scoped_session() -> None:
    """Verifica que los endpoints de lectura rápida puntual sigan utilizando get_async_session legítimamente."""
    routes_found = 0

    for route in executions_router.routes:
        if not isinstance(route, APIRoute):
            continue

        if (
            route.path == "/executions/{thread_id}"
            and route.methods is not None
            and "GET" in route.methods
        ):
            routes_found += 1
            all_dependencies = [d.call for d in route.dependant.dependencies]
            assert get_async_session in all_dependencies, (
                "El endpoint GET /executions/{thread_id} debe disponer de su sesión de lectura rápida."
            )

    assert routes_found == 1, "No se localizó la ruta GET /executions/{thread_id}."
