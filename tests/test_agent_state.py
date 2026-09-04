"""Tests unitarios para la especificación agnóstica de AgentState y StateGraph de LangGraph."""

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, StateGraph

from app.models import (
    AgentExecutionStatus,
    AgentInput,
    AgentState,
    ApprovalRecord,
    ApprovalStatus,
    AuditRecord,
    ExecutionError,
    ExecutionPlan,
    IntentModel,
    PlanStep,
    RiskLevel,
    StepExecutionRecord,
    StepStatus,
    append_reducer,
)


class TestAppendReducer:
    """Pruebas del reducer genérico append_reducer."""

    def test_append_reducer_with_none(self) -> None:
        assert append_reducer(None, None) == []
        assert append_reducer(["a"], None) == ["a"]
        assert append_reducer(None, ["b"]) == ["b"]

    def test_append_reducer_concatenation(self) -> None:
        left = [{"id": 1}]
        right = [{"id": 2}, {"id": 3}]
        result = append_reducer(left, right)
        assert result == [{"id": 1}, {"id": 2}, {"id": 3}]


class TestStateSubmodels:
    """Pruebas para los modelos operacionales estructurados."""

    def test_intent_model(self) -> None:
        intent = IntentModel(
            goal="Consultar estado del sistema",
            action_type="query",
            parameters={"target": "cluster-1"},
            confidence=0.95,
            reasoning="El usuario solicitó telemetría",
        )
        assert intent.goal == "Consultar estado del sistema"
        assert intent.action_type == "query"
        assert intent.parameters["target"] == "cluster-1"
        assert intent.confidence == 0.95
        assert intent.reasoning == "El usuario solicitó telemetría"

    def test_plan_and_steps(self) -> None:
        step1 = PlanStep(
            step_id="step-1",
            tool_name="status_checker",
            tool_args={"service": "api"},
            risk_level=RiskLevel.LOW,
            reversible=False,
        )
        step2 = PlanStep(
            step_id="step-2",
            tool_name="restart_service",
            tool_args={"service": "api"},
            risk_level=RiskLevel.HIGH,
            reversible=True,
        )
        plan = ExecutionPlan(
            plan_id="plan-001",
            goal="Restablecer servicio api",
            steps=[step1, step2],
            estimated_risk=RiskLevel.HIGH,
        )
        assert plan.plan_id == "plan-001"
        assert len(plan.steps) == 2
        assert plan.steps[1].reversible is True
        assert plan.estimated_risk == RiskLevel.HIGH

    def test_approval_record(self) -> None:
        record = ApprovalRecord(
            status=ApprovalStatus.APPROVED,
            approver="admin-operator",
            notes="Autorizado para mantenimiento nocturno",
        )
        assert record.status == ApprovalStatus.APPROVED
        assert record.approver == "admin-operator"
        assert record.rejection_reason is None

    def test_step_execution_record(self) -> None:
        rec = StepExecutionRecord(
            step_id="step-1",
            tool_name="status_checker",
            tool_args={"key": "val"},
            status=StepStatus.COMPLETED,
            output={"ok": True},
            duration_ms=12.5,
        )
        assert rec.step_id == "step-1"
        assert rec.status == StepStatus.COMPLETED
        assert rec.output == {"ok": True}

    def test_audit_record(self) -> None:
        audit = AuditRecord(
            event_type="workflow_started",
            actor="test_runner",
            details={"session": "s1"},
        )
        assert audit.event_type == "workflow_started"
        assert audit.actor == "test_runner"
        assert audit.details["session"] == "s1"

    def test_execution_error(self) -> None:
        err = ExecutionError(
            code="ERR_TIMEOUT",
            message="El servicio no respondió a tiempo",
            component="verifier_node",
            fatal=True,
        )
        assert err.code == "ERR_TIMEOUT"
        assert err.fatal is True


class TestAgentStateWithLangGraph:
    """Pruebas de mutación de estado y ejecución con LangGraph StateGraph."""

    def test_agent_state_generic_environment_snapshot(self) -> None:
        """Verifica que environment_snapshot acepta cualquier estructura de dominio sin ataduras."""
        state: AgentState = {
            "environment_snapshot": {
                "custom_metric": 42,
                "subsystem_status": "online",
            },
            "status": AgentExecutionStatus.IDLE,
        }
        assert state["environment_snapshot"] is not None
        assert state["environment_snapshot"]["custom_metric"] == 42
        assert state["status"] == AgentExecutionStatus.IDLE

    def test_agent_state_langgraph_flow_mutations(self) -> None:
        """Verifica un flujo completo de StateGraph mutando mensajes, trazas de auditoría y estado."""
        builder = StateGraph(AgentState)

        def observe_node(state: AgentState) -> dict[str, Any]:
            return {
                "status": AgentExecutionStatus.OBSERVING,
                "environment_snapshot": {"observed_value": "nominal"},
                "audit_trail": [
                    AuditRecord(
                        event_type="observe_completed",
                        details={"metric": "nominal"},
                    )
                ],
            }

        def reason_node(state: AgentState) -> dict[str, Any]:
            return {
                "status": AgentExecutionStatus.REASONING,
                "intent": IntentModel(
                    goal="Finalizar tarea de verificación",
                    action_type="conclude",
                ),
                "messages": [AIMessage(content="He analizado la observación.")],
                "audit_trail": [AuditRecord(event_type="reasoning_completed")],
            }

        def execute_node(state: AgentState) -> dict[str, Any]:
            return {
                "status": AgentExecutionStatus.RESOLVED,
                "execution_records": [
                    StepExecutionRecord(
                        step_id="step-end",
                        tool_name="noop",
                        status=StepStatus.COMPLETED,
                    )
                ],
                "audit_trail": [AuditRecord(event_type="execution_finished")],
                "is_resolved": True,
            }

        builder.add_node("observe", observe_node)
        builder.add_node("reason", reason_node)
        builder.add_node("execute", execute_node)

        builder.add_edge(START, "observe")
        builder.add_edge("observe", "reason")
        builder.add_edge("reason", "execute")
        builder.add_edge("execute", END)

        graph = builder.compile()

        initial_input: AgentState = {
            "request": AgentInput(
                execution_id="exec-state-01",
                thread_id="th-state-01",
                prompt="Ejecutar análisis",
            ),
            "messages": [HumanMessage(content="Ejecutar análisis")],
            "audit_trail": [AuditRecord(event_type="pipeline_initialized")],
            "status": AgentExecutionStatus.IDLE,
            "environment_snapshot": None,
            "errors": [],
            "execution_records": [],
        }

        final_state = graph.invoke(initial_input)

        # Verificación de canales con reducers
        assert len(final_state["messages"]) == 2
        assert isinstance(final_state["messages"][0], HumanMessage)
        assert isinstance(final_state["messages"][1], AIMessage)

        # Verificación de acumulación en audit_trail
        assert len(final_state["audit_trail"]) == 4
        event_types = [a.event_type for a in final_state["audit_trail"]]
        assert event_types == [
            "pipeline_initialized",
            "observe_completed",
            "reasoning_completed",
            "execution_finished",
        ]

        # Verificación de estado final y snapshots
        assert final_state["status"] == AgentExecutionStatus.RESOLVED
        assert final_state["is_resolved"] is True
        assert final_state["environment_snapshot"] == {"observed_value": "nominal"}
        assert len(final_state["execution_records"]) == 1
        assert final_state["intent"].goal == "Finalizar tarea de verificación"
