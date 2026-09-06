"""Motor de planificación de tareas en grafo acíclico dirigido (DAGPlannerEngine).

Genera secuencias estructuradas de pasos (PlanStep) con dependencias topológicas,
asigna niveles de riesgo estrictos (RiskLevel) y deriva planes automáticos a partir
de incidentes detectados en environment_snapshot o peticiones del usuario.
"""

import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from app.models.state import (
    AgentState,
    ExecutionPlan,
    IntentModel,
    PlanStep,
    StepStatus,
)
from app.models.tools import RiskLevel
from app.plugins.base import PlannerEngine

logger = logging.getLogger("jg_plugin_devops.planner")

_RISK_ORDER: dict[RiskLevel, int] = {
    RiskLevel.LOW: 1,
    RiskLevel.MEDIUM: 2,
    RiskLevel.HIGH: 3,
    RiskLevel.CRITICAL: 4,
}


def _compute_highest_risk(steps: list[PlanStep]) -> RiskLevel:
    """Calcula el riesgo más alto presente en la secuencia de pasos."""
    if not steps:
        return RiskLevel.LOW
    highest = max(steps, key=lambda s: _RISK_ORDER.get(s.risk_level, 1))
    return highest.risk_level


class DAGPlannerEngine(PlannerEngine):
    """Motor de planificación heurística y formulación de DAGs operacionales para DevOps."""

    def __init__(self) -> None:
        self._is_started: bool = False

    @property
    def name(self) -> str:
        """Identificador único del motor."""
        return "dag_planner"

    async def startup(self) -> None:
        """Inicialización del planificador."""
        logger.info("Iniciando DAGPlannerEngine...")
        self._is_started = True

    async def shutdown(self) -> None:
        """Liberación de recursos del planificador."""
        logger.info("Deteniendo DAGPlannerEngine...")
        self._is_started = False

    def create_plan(self, state: AgentState | None = None) -> ExecutionPlan:
        """Formula un ExecutionPlan con pasos estructurados, dependencias y riesgos evaluados.

        Este método es invocado automáticamente por el nodo 'plan' de LangGraph.
        """
        plan_id = f"plan-devops-{uuid.uuid4().hex[:8]}-{int(time.time())}"

        # 1. Resolver el objetivo (goal) y texto del prompt
        goal = "Plan de operaciones y mantenimiento DevOps"
        prompt_text = ""
        if state is not None:
            req = state.get("request")
            if req is not None and hasattr(req, "prompt"):
                prompt_text = str(req.prompt)

            intent = state.get("intent")
            if isinstance(intent, IntentModel):
                goal = intent.goal
            elif isinstance(intent, dict) and "goal" in intent:
                goal = str(intent["goal"])
            elif prompt_text:
                goal = prompt_text

        steps: list[PlanStep] = []

        # 2. Heurística 1: Plan de remediación a partir de incidentes detectados
        env_snapshot = (state.get("environment_snapshot") or {}) if state else {}
        incidents = env_snapshot.get("incidents") or []

        if incidents:
            steps = self._plan_from_incidents(incidents)

        # 3. Heurística 2: Plan derivado de la instrucción o prompt del usuario si no hay incidentes
        context_text = f"{prompt_text} {goal}".strip()
        if not steps and context_text:
            steps = self._plan_from_prompt(context_text)

        # 4. Fallback estándar si no se pudieron derivar pasos específicos
        if not steps:
            steps = [
                PlanStep(
                    step_id="step-1",
                    tool_name="inspect_infrastructure_status",
                    tool_args={"scope": "all"},
                    description="Inspeccionar telemetría y estado general de la infraestructura",
                    risk_level=RiskLevel.LOW,
                    reversible=False,
                    dependencies=[],
                    status=StepStatus.PENDING,
                )
            ]

        # 5. Cómputo del riesgo total y creación del plan
        estimated_risk = _compute_highest_risk(steps)

        plan = ExecutionPlan(
            plan_id=plan_id,
            goal=goal,
            steps=steps,
            estimated_risk=estimated_risk,
            created_at=datetime.now(UTC),
        )

        logger.info(
            "Plan DAG formulado [%s]: %d pasos, riesgo estimado '%s'",
            plan_id,
            len(steps),
            estimated_risk.value,
        )
        return plan

    def plan(self, state: AgentState | None = None) -> ExecutionPlan:
        """Alias compatible para invocar el planificador."""
        return self.create_plan(state)

    # ========================================================================
    # Heurísticas de Derivación de DAGs
    # ========================================================================

    def _plan_from_incidents(self, incidents: list[dict[str, Any] | Any]) -> list[PlanStep]:
        """Genera un DAG ordenado de diagnóstico, remediación y verificación para incidentes."""
        steps: list[PlanStep] = []
        step_counter = 1

        for inc in incidents:
            component = (
                inc.get("component", "host")
                if isinstance(inc, dict)
                else getattr(inc, "component", "host")
            )
            title = (
                inc.get("title", "Anomalía")
                if isinstance(inc, dict)
                else getattr(inc, "title", "Anomalía")
            )

            # Caso A: Incidente en Docker (Contenedor unhealthy o caído)
            if component == "docker":
                diag_id = f"step-{step_counter}"
                steps.append(
                    PlanStep(
                        step_id=diag_id,
                        tool_name="collect_container_logs",
                        tool_args={"title": title, "lines": 50},
                        description=f"Diagnosticar logs del contenedor afectado por: {title}",
                        risk_level=RiskLevel.LOW,
                        reversible=False,
                        dependencies=[],
                        status=StepStatus.PENDING,
                    )
                )
                step_counter += 1

                remed_id = f"step-{step_counter}"
                details = (
                    inc.get("details", {}) if isinstance(inc, dict) else getattr(inc, "details", {})
                )
                container_target = details.get("container") or title
                steps.append(
                    PlanStep(
                        step_id=remed_id,
                        tool_name="docker_restart",
                        tool_args={"container": container_target, "title": title},
                        description=f"Reiniciar contenedor para mitigar incidente: {title}",
                        risk_level=RiskLevel.HIGH,
                        reversible=True,
                        dependencies=[diag_id],
                        status=StepStatus.PENDING,
                    )
                )
                step_counter += 1

                verify_id = f"step-{step_counter}"
                steps.append(
                    PlanStep(
                        step_id=verify_id,
                        tool_name="verify_service_health",
                        tool_args={"component": component, "title": title},
                        description=f"Verificar recuperación de salud tras remediación de: {title}",
                        risk_level=RiskLevel.LOW,
                        reversible=False,
                        dependencies=[remed_id],
                        status=StepStatus.PENDING,
                    )
                )
                step_counter += 1

            # Caso B: Incidente en Host (CPU, Memoria, Disco)
            elif component == "host":
                diag_id = f"step-{step_counter}"
                steps.append(
                    PlanStep(
                        step_id=diag_id,
                        tool_name="inspect_resource_usage",
                        tool_args={"title": title},
                        description=f"Inspeccionar procesos de alto consumo asociados a: {title}",
                        risk_level=RiskLevel.LOW,
                        reversible=False,
                        dependencies=[],
                        status=StepStatus.PENDING,
                    )
                )
                step_counter += 1

                remed_id = f"step-{step_counter}"
                steps.append(
                    PlanStep(
                        step_id=remed_id,
                        tool_name="optimize_system_resources",
                        tool_args={"title": title},
                        description=f"Liberar búferes y balancear carga para mitigar: {title}",
                        risk_level=RiskLevel.MEDIUM,
                        reversible=True,
                        dependencies=[diag_id],
                        status=StepStatus.PENDING,
                    )
                )
                step_counter += 1

                verify_id = f"step-{step_counter}"
                steps.append(
                    PlanStep(
                        step_id=verify_id,
                        tool_name="verify_metrics_recovery",
                        tool_args={"title": title},
                        description=f"Comprobar normalización de métricas tras mitigar: {title}",
                        risk_level=RiskLevel.LOW,
                        reversible=False,
                        dependencies=[remed_id],
                        status=StepStatus.PENDING,
                    )
                )
                step_counter += 1

        return steps

    def _plan_from_prompt(self, prompt: str) -> list[PlanStep]:
        """Genera un DAG basado en palabras clave operacionales e intención del prompt."""
        p_lower = prompt.lower()
        steps: list[PlanStep] = []

        # Acciones destructivas -> CRITICAL
        if any(w in p_lower for w in ("eliminar", "destruir", "prune", "drop", "delete", "rm")):
            steps.append(
                PlanStep(
                    step_id="step-1",
                    tool_name="backup_resource",
                    tool_args={"instruction": prompt},
                    description="Crear copia de seguridad preventiva antes de proceder",
                    risk_level=RiskLevel.MEDIUM,
                    reversible=True,
                    dependencies=[],
                    status=StepStatus.PENDING,
                )
            )
            steps.append(
                PlanStep(
                    step_id="step-2",
                    tool_name="execute_destructive_operation",
                    tool_args={"instruction": prompt},
                    description=f"Ejecutar operación con riesgo de eliminación: {prompt}",
                    risk_level=RiskLevel.CRITICAL,
                    reversible=False,
                    dependencies=["step-1"],
                    status=StepStatus.PENDING,
                )
            )
            steps.append(
                PlanStep(
                    step_id="step-3",
                    tool_name="verify_system_integrity",
                    tool_args={"instruction": prompt},
                    description="Verificar integridad del sistema post-eliminación",
                    risk_level=RiskLevel.LOW,
                    reversible=False,
                    dependencies=["step-2"],
                    status=StepStatus.PENDING,
                )
            )

        # Acciones de mutación / reinicio -> HIGH
        elif any(
            w in p_lower
            for w in (
                "reiniciar",
                "restart",
                "reboot",
                "detener",
                "stop",
                "remediar",
                "deploy",
                "actualizar",
            )
        ):
            steps.append(
                PlanStep(
                    step_id="step-1",
                    tool_name="inspect_service_status",
                    tool_args={"instruction": prompt},
                    description="Comprobar estado pre-operacional del servicio",
                    risk_level=RiskLevel.LOW,
                    reversible=False,
                    dependencies=[],
                    status=StepStatus.PENDING,
                )
            )
            steps.append(
                PlanStep(
                    step_id="step-2",
                    tool_name="restart_service",
                    tool_args={"instruction": prompt},
                    description=f"Ejecutar reinicio o actualización requerida: {prompt}",
                    risk_level=RiskLevel.HIGH,
                    reversible=True,
                    dependencies=["step-1"],
                    status=StepStatus.PENDING,
                )
            )
            steps.append(
                PlanStep(
                    step_id="step-3",
                    tool_name="verify_service_status",
                    tool_args={"instruction": prompt},
                    description="Verificar disponibilidad y operatividad del servicio",
                    risk_level=RiskLevel.LOW,
                    reversible=False,
                    dependencies=["step-2"],
                    status=StepStatus.PENDING,
                )
            )

        # Acciones no destructivas de ajuste -> MEDIUM
        elif any(w in p_lower for w in ("limpiar", "clear", "reload", "recargar", "purgar")):
            steps.append(
                PlanStep(
                    step_id="step-1",
                    tool_name="reload_service_configuration",
                    tool_args={"instruction": prompt},
                    description=f"Recargar configuración o limpiar caché: {prompt}",
                    risk_level=RiskLevel.MEDIUM,
                    reversible=True,
                    dependencies=[],
                    status=StepStatus.PENDING,
                )
            )

        # Acciones de sólo lectura / auditoría -> LOW
        else:
            steps.append(
                PlanStep(
                    step_id="step-1",
                    tool_name="inspect_infrastructure_status",
                    tool_args={"instruction": prompt},
                    description=f"Consultar telemetría e inspeccionar estado: {prompt}",
                    risk_level=RiskLevel.LOW,
                    reversible=False,
                    dependencies=[],
                    status=StepStatus.PENDING,
                )
            )

        return steps
