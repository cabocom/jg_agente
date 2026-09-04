"""Tests unitarios e integrados para el ensamblador de grafos agnóstico GraphBuilder."""

import ast
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from app.core.graph import (
    GraphBuilder,
)
from app.core.registry import CapabilityRegistry
from app.models.io import AgentInput
from app.models.state import (
    AgentExecutionStatus,
    AgentState,
    ApprovalRecord,
    ApprovalStatus,
    ExecutionPlan,
    IntentModel,
    PlanStep,
    StepStatus,
    VerificationStatus,
)
from app.models.tools import AgentTool, RiskLevel, ToolResult
from app.plugins.base import ObserverEngine, PlannerEngine, VerifierEngine

# ==========================================================
# Mocks y Herramientas Auxiliares de Prueba
# ==========================================================


class MockObserver(ObserverEngine):
    @property
    def name(self) -> str:
        return "mock_observer"

    async def observe(self, state: AgentState) -> dict[str, Any]:
        return {"system_health": "100%", "nodes_online": 3}


class MockPlanner(PlannerEngine):
    @property
    def name(self) -> str:
        return "mock_planner"

    async def create_plan(self, state: AgentState) -> ExecutionPlan:
        return ExecutionPlan(
            plan_id="plan-mock-01",
            goal="Ejecutar diagnóstico y acción",
            steps=[
                PlanStep(
                    step_id="step-1",
                    tool_name="mock_safe_tool",
                    tool_args={"target": "service-a"},
                    description="Paso seguro 1",
                    risk_level=RiskLevel.LOW,
                    reversible=False,
                )
            ],
            estimated_risk=RiskLevel.LOW,
        )


class MockVerifier(VerifierEngine):
    def __init__(self, should_fail: bool = False) -> None:
        self.should_fail = should_fail

    @property
    def name(self) -> str:
        return "mock_verifier"

    async def verify(self, state: AgentState) -> dict[str, Any]:
        status = VerificationStatus.FAIL if self.should_fail else VerificationStatus.PASS
        return {"status": status.value, "metric_delta": 0.0}


def dummy_safe_func(**kwargs: Any) -> ToolResult:
    return ToolResult(success=True, output="safe_executed")


def dummy_high_risk_func(**kwargs: Any) -> ToolResult:
    return ToolResult(success=True, output="high_risk_executed")


def dummy_reversible_func(**kwargs: Any) -> ToolResult:
    return ToolResult(
        success=True,
        output="reversible_executed",
        rollback_context={"backup_id": "bak-123"},
    )


def dummy_rollback_func(ctx: dict[str, Any]) -> ToolResult:
    return ToolResult(success=True, output=f"rolled_back_{ctx.get('backup_id')}")


# ==========================================================
# Suites de Prueba para GraphBuilder
# ==========================================================


class TestGraphBuilderMinimal:
    """Pruebas para grafos con capacidades mínimas."""

    def test_minimal_topology(self) -> None:
        registry = CapabilityRegistry()
        builder = GraphBuilder(registry)
        topology = builder.get_topology()

        assert topology.has_observer is False
        assert topology.has_planner is False
        assert topology.has_verifier is False
        assert topology.has_risk_assessment is False
        assert topology.has_human_approval is False
        assert topology.has_rollback is False
        assert topology.nodes == ["reason", "execute", "conclude"]
        assert topology.conditional_nodes == []

    @pytest.mark.asyncio
    async def test_minimal_graph_compilation_and_snapshot(self) -> None:
        registry = CapabilityRegistry()
        safe_tool = AgentTool(
            name="mock_safe_tool",
            description="Herramienta segura",
            category="test",
            func=dummy_safe_func,
            risk_level=RiskLevel.LOW,
        )
        registry.register_tool(safe_tool)

        builder = GraphBuilder(registry)
        graph = builder.build()

        thread_id = "test-thread-minimal-01"
        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}

        initial_state: AgentState = {
            "request": AgentInput(
                execution_id="exec-min-01",
                thread_id=thread_id,
                prompt="Hola, ¿puedes ejecutar mock_safe_tool?",
            ),
            "messages": [HumanMessage(content="Hola, ¿puedes ejecutar mock_safe_tool?")],
            "status": AgentExecutionStatus.IDLE,
        }

        # Ejecución sobre el grafo compilado
        result = await graph.ainvoke(initial_state, config=config)

        # Validación del resultado
        assert result["status"] == AgentExecutionStatus.RESOLVED
        assert result["is_resolved"] is True
        assert len(result["audit_trail"]) >= 3

        # Validación estricta del criterio de aceptación: StateSnapshot funcional
        snapshot = await graph.aget_state(config)
        assert snapshot is not None
        assert type(snapshot).__name__ == "StateSnapshot"
        assert snapshot.values["status"] == AgentExecutionStatus.RESOLVED
        assert snapshot.values["is_resolved"] is True
        assert snapshot.config["configurable"]["thread_id"] == thread_id


class TestGraphBuilderFullTopology:
    """Pruebas para grafos con capacidades completas registradas."""

    def test_full_capability_topology_inspection(self) -> None:
        registry = CapabilityRegistry()
        registry.register_engine(MockObserver())
        registry.register_engine(MockPlanner())
        registry.register_engine(MockVerifier())

        high_risk_tool = AgentTool(
            name="mock_high_risk_tool",
            description="Herramienta de alto riesgo",
            category="test",
            func=dummy_high_risk_func,
            risk_level=RiskLevel.HIGH,
            required_permissions=["admin"],
        )
        reversible_tool = AgentTool(
            name="mock_reversible_tool",
            description="Herramienta reversible",
            category="test",
            func=dummy_reversible_func,
            rollback_func=dummy_rollback_func,
            reversible=True,
            risk_level=RiskLevel.LOW,
        )
        registry.register_tool(high_risk_tool)
        registry.register_tool(reversible_tool)

        builder = GraphBuilder(registry)
        topology = builder.get_topology()

        assert topology.has_observer is True
        assert topology.has_planner is True
        assert topology.has_verifier is True
        assert topology.has_risk_assessment is True
        assert topology.has_human_approval is True
        assert topology.has_rollback is True

        expected_nodes = [
            "observe",
            "reason",
            "plan",
            "risk_assess",
            "human_approval",
            "execute",
            "verify",
            "rollback",
            "conclude",
        ]
        assert topology.nodes == expected_nodes

    @pytest.mark.asyncio
    async def test_full_capability_execution_flow(self) -> None:
        registry = CapabilityRegistry()
        registry.register_engine(MockObserver())
        registry.register_engine(MockPlanner())
        registry.register_engine(MockVerifier(should_fail=False))

        safe_tool = AgentTool(
            name="mock_safe_tool",
            description="Herramienta segura",
            category="test",
            func=dummy_safe_func,
            risk_level=RiskLevel.LOW,
        )
        registry.register_tool(safe_tool)

        builder = GraphBuilder(registry)
        graph = builder.build()

        thread_id = "test-thread-full-01"
        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}

        initial_state: AgentState = {
            "request": AgentInput(
                execution_id="exec-full-01",
                thread_id=thread_id,
                prompt="Ejecutar ciclo completo con observador, planificador y verificador",
            ),
            "messages": [HumanMessage(content="Ejecutar ciclo completo")],
            "status": AgentExecutionStatus.IDLE,
        }

        result = await graph.ainvoke(initial_state, config=config)

        # Verificaciones del flujo
        assert result["status"] == AgentExecutionStatus.RESOLVED
        assert result["environment_snapshot"] == {"system_health": "100%", "nodes_online": 3}
        assert result["plan"] is not None
        assert len(result["execution_records"]) >= 1
        assert len(result["verification_results"]) >= 1
        assert result["verification_results"][0]["status"] == VerificationStatus.PASS.value

        # Inspección del StateSnapshot
        snapshot = await graph.aget_state(config)
        assert snapshot is not None
        assert type(snapshot).__name__ == "StateSnapshot"
        assert snapshot.values["environment_snapshot"]["system_health"] == "100%"


class TestGraphBuilderHITL:
    """Pruebas para interacción humana (HITL) e interrupciones en el checkpointer."""

    @pytest.mark.asyncio
    async def test_human_in_the_loop_interruption_and_resume(self) -> None:
        registry = CapabilityRegistry()
        high_risk_tool = AgentTool(
            name="deploy_critical_update",
            description="Actualización crítica",
            category="test",
            func=dummy_high_risk_func,
            risk_level=RiskLevel.HIGH,
            required_permissions=["deploy:write"],
        )
        registry.register_tool(high_risk_tool)

        class HighRiskPlanner(PlannerEngine):
            @property
            def name(self) -> str:
                return "high_risk_planner"

            async def create_plan(self, state: AgentState) -> ExecutionPlan:
                return ExecutionPlan(
                    plan_id="plan-hr-01",
                    goal="Desplegar parche crítico",
                    steps=[
                        PlanStep(
                            step_id="step-hr-1",
                            tool_name="deploy_critical_update",
                            risk_level=RiskLevel.HIGH,
                        )
                    ],
                    estimated_risk=RiskLevel.HIGH,
                )

        registry.register_engine(HighRiskPlanner())

        # Ensamblar con pausa antes de human_approval
        builder = GraphBuilder(registry)
        graph = builder.build(interrupt_before=["human_approval"])

        thread_id = "test-thread-hitl-01"
        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}

        initial_state: AgentState = {
            "request": AgentInput(
                execution_id="exec-hitl-01",
                thread_id=thread_id,
                prompt="Desplegar parche crítico en producción",
            ),
            "messages": [HumanMessage(content="Desplegar parche crítico")],
            "status": AgentExecutionStatus.IDLE,
        }

        # 1. Invocación inicial: debe pausarse antes de human_approval
        await graph.ainvoke(initial_state, config=config)

        snapshot_paused = await graph.aget_state(config)
        assert snapshot_paused is not None
        # Comprobar que el siguiente nodo pendiente es human_approval
        assert snapshot_paused.next == ("human_approval",)
        assert snapshot_paused.values["human_intervention_required"] is True

        # 2. Simular aprobación humana actualizando el StateSnapshot
        await graph.aupdate_state(
            config,
            {
                "approval": ApprovalRecord(
                    status=ApprovalStatus.APPROVED,
                    approver="sre-lead",
                    notes="Aprobado para ventana de mantenimiento",
                )
            },
        )

        # 3. Reanudar la ejecución desde el checkpoint
        resumed_result = await graph.ainvoke(None, config=config)

        # Comprobar que finalizó con éxito tras la aprobación
        assert resumed_result["status"] == AgentExecutionStatus.RESOLVED
        assert resumed_result["is_resolved"] is True
        rec = resumed_result["execution_records"][0]
        rec_status = getattr(rec, "status", None) or (
            rec.get("status") if isinstance(rec, dict) else None
        )
        assert rec_status == StepStatus.COMPLETED

        final_snapshot = await graph.aget_state(config)
        assert final_snapshot.next == ()
        approval_val = final_snapshot.values["approval"]
        approval_status = getattr(approval_val, "status", None) or (
            approval_val.get("status") if isinstance(approval_val, dict) else None
        )
        assert approval_status in (ApprovalStatus.APPROVED, ApprovalStatus.APPROVED.value)


class TestGraphBuilderRollback:
    """Pruebas de flujo de rollback ante fallos de verificación."""

    @pytest.mark.asyncio
    async def test_verification_failure_triggers_rollback(self) -> None:
        registry = CapabilityRegistry()
        reversible_tool = AgentTool(
            name="modifiable_param",
            description="Parámetro modificable",
            category="test",
            func=dummy_reversible_func,
            rollback_func=dummy_rollback_func,
            reversible=True,
            risk_level=RiskLevel.LOW,
        )
        registry.register_tool(reversible_tool)

        # Verificador que falla explícitamente
        registry.register_engine(MockVerifier(should_fail=True))

        class ReversiblePlanner(PlannerEngine):
            @property
            def name(self) -> str:
                return "rev_planner"

            async def create_plan(self, state: AgentState) -> ExecutionPlan:
                return ExecutionPlan(
                    plan_id="plan-rev-01",
                    goal="Modificar y verificar",
                    steps=[
                        PlanStep(
                            step_id="step-rev-1",
                            tool_name="modifiable_param",
                            reversible=True,
                            risk_level=RiskLevel.LOW,
                        )
                    ],
                )

        registry.register_engine(ReversiblePlanner())

        builder = GraphBuilder(registry)
        graph = builder.build()

        thread_id = "test-thread-rollback-01"
        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}

        initial_state: AgentState = {
            "request": AgentInput(
                execution_id="exec-rb-01",
                thread_id=thread_id,
                prompt="Ejecutar acción reversible que fallará verificación",
            ),
            "status": AgentExecutionStatus.IDLE,
        }

        result = await graph.ainvoke(initial_state, config=config)

        # Comprobar que se ejecutó rollback
        assert len(result["rollback_records"]) == 1
        assert result["rollback_records"][0]["tool_name"] == "modifiable_param"
        assert result["rollback_records"][0]["success"] is True
        assert "bak-123" in result["rollback_records"][0]["output"]

        snapshot = await graph.aget_state(config)
        assert len(snapshot.values["rollback_records"]) == 1


class TestGraphBuilderAgnosticism:
    """Pruebas estrictas de agnosticismo arquitectónico: CERO condicionales por tipo de dominio."""

    def test_no_domain_specific_branches_in_source(self) -> None:
        graph_file = Path(__file__).resolve().parent.parent / "app" / "core" / "graph.py"
        source = graph_file.read_text(encoding="utf-8")

        # Inspección léxica
        forbidden_terms = [
            "conversational",
            "devops",
            "asterisk",
            "telegram",
            "is_conversational",
            "is_devops",
            "agent_type",
        ]

        for term in forbidden_terms:
            assert term not in source, (
                f"Violación de Agnosticismo Radical: Término prohibido '{term}' "
                f"encontrado en app/core/graph.py"
            )

        # Inspección de AST para validar que no hay condicionales comparando nombres de dominio
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.If):
                for sub in ast.walk(node.test):
                    if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                        for term in forbidden_terms:
                            assert term not in sub.value.lower(), (
                                f"Bifurcación condicional sobre '{term}' detectada en AST."
                            )


class TestGraphBuilderNodeOverrides:
    """Pruebas para sobreescritura de nodos personalizados."""

    @pytest.mark.asyncio
    async def test_custom_node_override(self) -> None:
        registry = CapabilityRegistry()

        custom_executed = False

        async def custom_reason(state: AgentState) -> dict[str, Any]:
            nonlocal custom_executed
            custom_executed = True
            return {
                "status": AgentExecutionStatus.REASONING,
                "intent": IntentModel(
                    goal="Intención custom",
                    action_type="conclude",
                ),
            }

        builder = GraphBuilder(registry, node_overrides={"reason": custom_reason})
        graph = builder.build()

        config: RunnableConfig = {"configurable": {"thread_id": "test-override"}}
        result = await graph.ainvoke(
            {"request": AgentInput(execution_id="1", thread_id="t1", prompt="test")},
            config=config,
        )

        assert custom_executed is True
        assert result["intent"].goal == "Intención custom"
