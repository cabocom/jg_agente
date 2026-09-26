"""Motor de planificación de tareas en grafo acíclico dirigido (DAGPlannerEngine).

Genera secuencias estructuradas de pasos (PlanStep) con dependencias topológicas,
asigna niveles de riesgo estrictos (RiskLevel) y deriva planes automáticos a partir
de incidentes detectados en environment_snapshot o peticiones del usuario.
"""

import json
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

        # 2. Heurística 0: Si el LLM ya seleccionó llamadas a herramientas en reason_node, generar pasos correspondientes
        tool_calls: list[dict[str, Any]] = []
        if state is not None:
            intent_val = state.get("intent")
            if isinstance(intent_val, IntentModel) and intent_val.action_type == "act":
                tool_calls = intent_val.parameters.get("tool_calls") or []
            elif isinstance(intent_val, dict) and intent_val.get("action_type") == "act":
                tool_calls = intent_val.get("parameters", {}).get("tool_calls") or []

        if tool_calls:
            for idx, tc in enumerate(tool_calls, start=1):
                t_name = tc.get("name") or tc.get("tool_name", f"tool-{idx}")
                t_args = tc.get("args") or tc.get("tool_args", {})
                if isinstance(t_args, str):
                    try:
                        t_args = json.loads(t_args)
                    except Exception:
                        t_args = {"raw_args": t_args}
                t_risk = RiskLevel.LOW
                if any(k in t_name.lower() for k in ("restart", "reiniciar", "stop", "detener")):
                    t_risk = RiskLevel.HIGH
                elif any(k in t_name.lower() for k in ("delete", "borrar", "destroy", "prune")):
                    t_risk = RiskLevel.CRITICAL
                steps.append(
                    PlanStep(
                        step_id=f"step-{idx}",
                        tool_name=t_name,
                        tool_args=t_args,
                        description=f"Ejecución de herramienta '{t_name}'",
                        risk_level=t_risk,
                        reversible=t_risk in (RiskLevel.HIGH, RiskLevel.MEDIUM),
                        dependencies=[f"step-{idx - 1}"] if idx > 1 else [],
                        status=StepStatus.PENDING,
                    )
                )

        # 3. Heurística 1: Plan derivado de la instrucción o prompt del usuario si no hay tool_calls
        if not steps:
            context_text = f"{prompt_text} {goal}".strip()
            if context_text and not any(
                w in context_text.lower() for w in ("remediar incidentes", "reparar incidentes")
            ):
                steps = self._plan_from_prompt(context_text)

        # 4. Heurística 2: Plan de remediación a partir de incidentes detectados si no hay pasos
        if not steps:
            env_snapshot = (state.get("environment_snapshot") or {}) if state else {}
            incidents = env_snapshot.get("incidents") or []
            if incidents:
                steps = self._plan_from_incidents(incidents)

        # 4. Fallback estándar si no se pudieron derivar pasos específicos
        if not steps:
            steps = []

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

        # Acciones de consulta o listado de contenedores / docker / estado de servicios
        elif any(
            w in p_lower
            for w in (
                "contenedor",
                "contenedores",
                "container",
                "containers",
                "docker ps",
                "listar",
                "listado",
                "cuantos",
                "cuántos",
                "servicios",
            )
        ):
            steps.append(
                PlanStep(
                    step_id="step-1",
                    tool_name="docker_list_containers",
                    tool_args={"all": True},
                    description=f"Listar y comprobar estado de los contenedores Docker: {prompt}",
                    risk_level=RiskLevel.LOW,
                    reversible=False,
                    dependencies=[],
                    status=StepStatus.PENDING,
                )
            )

        # Acciones de consulta de logs
        elif any(w in p_lower for w in ("log", "logs", "trazas", "registro")):
            target_container = "jg_agente_conversacional"
            known_containers = [
                "jg_agente_conversacional",
                "jg_agente_devops",
                "jg_agente_datosgob",
                "jg_dashboard",
                "jg_agente_postgres",
                "jg_dashboard_postgres",
            ]
            for c_name in known_containers:
                if c_name in p_lower or c_name.replace("jg_", "") in p_lower:
                    target_container = c_name
                    break

            steps.append(
                PlanStep(
                    step_id="step-1",
                    tool_name="docker_logs",
                    tool_args={"container": target_container, "tail": 50},
                    description=f"Recuperar últimas trazas y logs del contenedor '{target_container}': {prompt}",
                    risk_level=RiskLevel.LOW,
                    reversible=False,
                    dependencies=[],
                    status=StepStatus.PENDING,
                )
            )

        # Acciones de inspección detallada de contenedor
        elif any(w in p_lower for w in ("inspect", "inspeccionar", "detalle", "detalles")):
            target_container = "jg_agente_conversacional"
            known_containers = [
                "jg_agente_conversacional",
                "jg_agente_devops",
                "jg_agente_datosgob",
                "jg_dashboard",
                "jg_agente_postgres",
                "jg_dashboard_postgres",
            ]
            for c_name in known_containers:
                if c_name in p_lower or c_name.replace("jg_", "") in p_lower:
                    target_container = c_name
                    break

            steps.append(
                PlanStep(
                    step_id="step-1",
                    tool_name="docker_inspect_container",
                    tool_args={"container": target_container},
                    description=f"Inspeccionar configuración y telemetría del contenedor '{target_container}': {prompt}",
                    risk_level=RiskLevel.LOW,
                    reversible=False,
                    dependencies=[],
                    status=StepStatus.PENDING,
                )
            )

        # Acciones de sólo lectura / auditoría general -> LOW
        elif any(
            w in p_lower
            for w in (
                "consultar",
                "auditar",
                "telemetria",
                "telemetría",
                "status",
                "estado",
                "monitor",
                "métricas",
                "metricas",
            )
        ):
            steps.append(
                PlanStep(
                    step_id="step-1",
                    tool_name="docker_list_containers",
                    tool_args={"all": True},
                    description=f"Consultar estado de contenedores e infraestructura: {prompt}",
                    risk_level=RiskLevel.LOW,
                    reversible=False,
                    dependencies=[],
                    status=StepStatus.PENDING,
                )
            )

        return steps
