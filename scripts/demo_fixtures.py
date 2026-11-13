# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: MIT License
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Motores cognitivos simulados y herramientas de demostración para escenarios manuales."""

from datetime import UTC, datetime
from typing import Any

from jg_sdk.contracts import (
    ObserverEngine,
    PlannerEngine,
    RiskLevel,
    ToolResult,
    VerifierEngine,
)
from jg_sdk.models import ExecutionPlan, PlanStep

from app.core.state import AgentState

# ==========================================================
# Motores Cognitivos de Demostración
# ==========================================================


class DemoObserver(ObserverEngine):
    """Motor de observación de telemetría para la prueba."""

    @property
    def name(self) -> str:
        return "demo_telemetry_observer"

    async def observe(self, state: AgentState) -> dict[str, Any]:
        return {
            "cluster_id": "k8s-prod-eu-west-1",
            "active_nodes": 6,
            "cpu_utilization_pct": 78.4,
            "memory_usage_pct": 84.1,
            "alert_status": "HIGH_LOAD_WARNING",
            "timestamp": datetime.now(UTC).isoformat(),
        }


class DemoPlanner(PlannerEngine):
    """Motor de formulación de planes ordenados para la prueba."""

    @property
    def name(self) -> str:
        return "demo_dag_planner"

    async def plan(self, state: AgentState) -> ExecutionPlan:
        return ExecutionPlan(
            plan_id="plan-demo-01",
            goal="Optimizar recursos y reiniciar nodo crítico de producción con alta carga",
            steps=[
                PlanStep(
                    step_id="step-1",
                    tool_name="consultar_metricas_nodo",
                    description="Consultar telemetría detallada del nodo afectado",
                    risk_level=RiskLevel.LOW,
                    reversible=False,
                ),
                PlanStep(
                    step_id="step-2",
                    tool_name="reiniciar_nodo_produccion",
                    description="Reiniciar nodo k8s worker-03 en caliente (Acción de Riesgo)",
                    risk_level=RiskLevel.HIGH,
                    reversible=True,
                    dependencies=["step-1"],
                ),
            ],
            estimated_risk=RiskLevel.HIGH,
        )


class DemoVerifier(VerifierEngine):
    """Motor de verificación que puede simular aprobación o anomalía."""

    def __init__(self, simulate_failure: bool = False) -> None:
        self.simulate_failure = simulate_failure

    @property
    def name(self) -> str:
        return "demo_health_verifier"

    async def verify(self, state: AgentState) -> dict[str, Any]:
        if self.simulate_failure:
            return {
                "status": "fail",
                "reason": "Anomalía post-ejecución: El servicio reporta latency_ms=1850ms y errores 502.",
                "checks": {"http_probe": 502, "healthy": False},
            }
        return {
            "status": "pass",
            "checks": {"http_probe": 200, "latency_ms": 14.2, "healthy": True},
        }


# ==========================================================
# Herramientas de Demostración
# ==========================================================


def func_consultar_metricas(**kwargs: Any) -> ToolResult:
    return ToolResult(
        success=True,
        output={"worker_id": "worker-03", "status": "Ready", "pod_count": 42},
        duration_ms=45.0,
    )


def func_reiniciar_nodo(**kwargs: Any) -> ToolResult:
    # Genera rollback_context para permitir compensación
    return ToolResult(
        success=True,
        output="Nodo worker-03 reiniciado satisfactoriamente.",
        duration_ms=180.0,
        rollback_context={
            "backup_state_id": "snap-worker-03-pre-reboot",
            "action": "restore_previous_kernel_state",
        },
    )


def rollback_reiniciar_nodo(ctx: dict[str, Any]) -> ToolResult:
    snap_id = ctx.get("backup_state_id", "desconocido")
    return ToolResult(
        success=True,
        output=f"Compensación ejecutada con éxito: Restaurado snapshot de contingencia '{snap_id}'.",
        duration_ms=95.0,
    )


# ==========================================================
# Constantes de Formato y Colores para Terminal
# ==========================================================

C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_CYAN = "\033[36m"
C_GREEN = "\033[32m"
C_YELLOW = "\033[33m"
C_RED = "\033[31m"
C_BLUE = "\033[34m"
C_MAGENTA = "\033[35m"
C_DIM = "\033[2m"

__all__ = [
    "C_BLUE",
    "C_BOLD",
    "C_CYAN",
    "C_DIM",
    "C_GREEN",
    "C_MAGENTA",
    "C_RED",
    "C_RESET",
    "C_YELLOW",
    "DemoObserver",
    "DemoPlanner",
    "DemoVerifier",
    "func_consultar_metricas",
    "func_reiniciar_nodo",
    "print_banner",
    "rollback_reiniciar_nodo",
]


def print_banner() -> None:
    print(f"\n{C_CYAN}{C_BOLD}{'=' * 70}{C_RESET}")
    print(f"{C_CYAN}{C_BOLD}   🤖 JG_AGENTE — DEMOSTRACIÓN DE EJECUCIÓN MANUAL COGNITIVA{C_RESET}")
    print(f"{C_CYAN}{C_BOLD}   LangGraph Execution Plane · HITL · Rollback · Verificación{C_RESET}")
    print(f"{C_CYAN}{C_BOLD}{'=' * 70}{C_RESET}\n")

