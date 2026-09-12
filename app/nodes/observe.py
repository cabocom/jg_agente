"""Nodo opcional de observación (observe) para jg_agente.

Se activa condicionalmente si existe un ObserverEngine registrado en CapabilityRegistry.
Invoca el motor de forma polimórfica para recolectar telemetría y estado de infraestructura,
consolidando el resultado en environment_snapshot dentro de AgentState de forma agnóstica.
"""

import inspect
import logging
import time
from datetime import UTC, datetime
from typing import Any

from app.core.registry import CapabilityRegistry
from app.models.state import (
    AgentExecutionStatus,
    AgentState,
    AuditRecord,
    CognitiveStepRecord,
    ExecutionError,
)
from app.plugins.base import BaseEngine, ObserverEngine

logger = logging.getLogger("jg_agente.nodes.observe")


async def observe_node(
    state: AgentState,
    registry: CapabilityRegistry | None = None,
    engine: ObserverEngine | BaseEngine | None = None,
) -> dict[str, Any]:
    """Ejecuta la captura de telemetría y estado del entorno mediante un ObserverEngine.

    Args:
        state: Estado global actual de LangGraph (AgentState).
        registry: Catálogo de capacidades registrado opcional.
        engine: Instancia directa de ObserverEngine (prioritaria sobre el catálogo).

    Returns:
        Mutaciones del estado para LangGraph (status, environment_snapshot, audit_trail y opcionalmente errors).
    """
    # 1. Resolver el motor de observación
    observer = engine
    if observer is None and registry is not None:
        observer = registry.get_observer()

    # 2. Si no hay observer registrado, actuar como no-op seguro
    if observer is None:
        logger.debug("No se ha detectado ningún ObserverEngine registrado. Omitiendo observación.")
        return {
            "status": AgentExecutionStatus.OBSERVING,
            "environment_snapshot": {},
            "audit_trail": [
                AuditRecord(
                    event_type="observe_completed",
                    actor="core",
                    details={"engine": "none", "keys": [], "skipped": True},
                )
            ],
        }

    start_time = time.perf_counter()
    snapshot: dict[str, Any] = {}
    errors: list[ExecutionError] = []

    # 3. Localizar el método invocable del motor (observe, discover, collect)
    observe_fn = None
    for candidate in ("observe", "discover", "collect"):
        attr = getattr(observer, candidate, None)
        if callable(attr):
            observe_fn = attr
            break

    # 4. Invocar el motor de observación polimórficamente
    if observe_fn is not None:
        try:
            # Inspeccionar parámetros aceptados para soportar firmas (state) o sin argumentos ()
            call_with_state = True
            try:
                sig = inspect.signature(observe_fn)
                call_with_state = len(sig.parameters) > 0
            except (TypeError, ValueError):
                call_with_state = True

            res = observe_fn(state) if call_with_state else observe_fn()
            raw = await res if inspect.iscoroutine(res) else res

            if isinstance(raw, dict):
                snapshot = dict(raw)
            elif raw is not None:
                snapshot = {"observed": raw}
            else:
                snapshot = {}
        except Exception as err:
            logger.exception("Excepción durante la observación en el motor %s", observer.name)
            errors.append(
                ExecutionError(
                    code="OBSERVER_EXECUTION_ERROR",
                    message=f"Fallo durante la observación en el motor '{observer.name}': {err}",
                    component="observe",
                    fatal=False,
                )
            )
            snapshot = {}
    else:
        # Si el motor no expone método específico pero está registrado
        snapshot = {"observer": observer.name, "status": "observed"}

    duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

    # 5. Registrar traza de auditoría inmutable
    audit = AuditRecord(
        event_type="observe_completed",
        actor=observer.name,
        details={
            "engine": observer.name,
            "keys": list(snapshot.keys()),
            "duration_ms": duration_ms,
            "has_errors": len(errors) > 0,
        },
    )

    cognitive_step = CognitiveStepRecord(
        step_id=f"cog_observe_{int(time.time() * 1000)}",
        node="observe",
        title=f"Descubrimiento y Observación: {observer.name}",
        action="Inspección de Infraestructura y Telemetría",
        description=(
            f"El motor de observación '{observer.name}' recopiló telemetría y estado del entorno "
            f"({len(snapshot)} variables/recursos detectados)."
        ),
        status="completed" if not errors else "failed",
        details={
            "engine": observer.name,
            "keys": list(snapshot.keys()),
            "snapshot_summary": {k: str(v)[:150] for k, v in list(snapshot.items())[:5]},
        },
        duration_ms=duration_ms,
        timestamp=datetime.now(UTC),
    )

    updates: dict[str, Any] = {
        "status": AgentExecutionStatus.OBSERVING,
        "environment_snapshot": snapshot,
        "cognitive_steps": [cognitive_step],
        "audit_trail": [audit],
    }
    if errors:
        updates["errors"] = errors

    return updates
