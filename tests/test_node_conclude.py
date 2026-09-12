"""Tests unitarios e integrados para el nodo base de conclusión (conclude)."""

from datetime import UTC, datetime, timedelta

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig

from app.core.graph import GraphBuilder
from app.core.registry import CapabilityRegistry
from app.models.io import AgentInput, AgentOutput, ExecutionStatus
from app.models.state import (
    AgentExecutionStatus,
    AgentState,
    EvaluationRecord,
    ExecutionError,
    GoalStatus,
    IntentModel,
    StepExecutionRecord,
    StepStatus,
)
from app.models.tools import AgentTool, RiskLevel, ToolResult
from app.nodes.conclude import conclude_node


def dummy_safe_tool(param: str = "") -> ToolResult:
    return ToolResult(success=True, output=f"dummy_{param}", duration_ms=12.5)


@pytest.fixture
def sample_registry() -> CapabilityRegistry:
    registry = CapabilityRegistry()
    registry.register_tool(
        AgentTool(
            name="safe_tool",
            description="Herramienta segura de prueba",
            category="test",
            func=dummy_safe_tool,
            risk_level=RiskLevel.LOW,
        )
    )
    return registry


class TestConcludeNode:
    """Pruebas unitarias para el nodo de conclusión."""

    @pytest.mark.asyncio
    async def test_conclude_node_direct_success(self) -> None:
        """Verifica conclusión exitosa a partir de respuesta conversacional del LLM."""
        state: AgentState = {
            "request": AgentInput(
                execution_id="exec-dir-01",
                thread_id="thread-dir-01",
                prompt="Hola, ¿cómo estás?",
            ),
            "messages": [
                HumanMessage(content="Hola, ¿cómo estás?"),
                AIMessage(content="¡Hola! Estoy listo para asistirte."),
            ],
            "intent": IntentModel(
                goal="Saludo",
                action_type="conclude",
                parameters={"response": "¡Hola! Estoy listo para asistirte."},
            ),
            "status": AgentExecutionStatus.REASONING,
        }

        result = await conclude_node(state)

        assert result["status"] == AgentExecutionStatus.RESOLVED
        assert result["is_resolved"] is True
        assert "output" in result

        output = result["output"]
        assert isinstance(output, AgentOutput)
        assert output.execution_id == "exec-dir-01"
        assert output.thread_id == "thread-dir-01"
        assert output.status == ExecutionStatus.COMPLETED
        assert output.response == "¡Hola! Estoy listo para asistirte."
        assert output.error is None
        assert output.execution_time_ms >= 0.0

        # Verificación de traza de auditoría
        assert len(result["audit_trail"]) == 1
        audit = result["audit_trail"][0]
        assert audit.event_type == "execution_concluded"
        assert audit.details["final_status"] == ExecutionStatus.COMPLETED.value
        assert audit.details["is_resolved"] is True

    @pytest.mark.asyncio
    async def test_conclude_node_from_execution_records(self) -> None:
        """Verifica conclusión a partir de herramientas ejecutadas con éxito."""
        records = [
            StepExecutionRecord(
                step_id="step-1",
                tool_name="safe_tool",
                tool_args={"param": "v1"},
                status=StepStatus.COMPLETED,
                output="dummy_v1",
                duration_ms=45.0,
            ),
            StepExecutionRecord(
                step_id="step-2",
                tool_name="safe_tool",
                tool_args={"param": "v2"},
                status=StepStatus.COMPLETED,
                output="dummy_v2",
                duration_ms=55.0,
            ),
        ]

        state: AgentState = {
            "request": AgentInput(
                execution_id="exec-tools-01",
                thread_id="thread-tools-01",
                prompt="Ejecutar pasos 1 y 2",
            ),
            "execution_records": records,
            "status": AgentExecutionStatus.EXECUTING,
        }

        result = await conclude_node(state)

        assert result["status"] == AgentExecutionStatus.RESOLVED
        assert result["is_resolved"] is True

        output = result["output"]
        assert isinstance(output, AgentOutput)
        assert output.status == ExecutionStatus.COMPLETED
        assert "Herramientas ejecutadas con éxito" in output.response
        assert output.data is not None
        assert output.data["steps_count"] == 2
        assert output.execution_time_ms >= 100.0  # suma de 45.0 + 55.0

    @pytest.mark.asyncio
    async def test_conclude_node_captures_errors_as_failed(self) -> None:
        """Verifica que errores fatales o pasos fallidos marquen status=FAILED."""
        records = [
            StepExecutionRecord(
                step_id="step-err",
                tool_name="failing_tool",
                status=StepStatus.FAILED,
                error="Timeout en API externa",
                duration_ms=30.0,
            )
        ]
        errors = [
            ExecutionError(
                code="TOOL_EXECUTION_FAILED",
                message="Timeout en API externa",
                component="execute",
                fatal=True,
            )
        ]

        state: AgentState = {
            "request": AgentInput(
                execution_id="exec-fail-01",
                thread_id="thread-fail-01",
                prompt="Acción que fallará",
            ),
            "execution_records": records,
            "errors": errors,
            "status": AgentExecutionStatus.FAILED,
        }

        result = await conclude_node(state)

        assert result["status"] == AgentExecutionStatus.FAILED
        assert result["is_resolved"] is False

        output = result["output"]
        assert isinstance(output, AgentOutput)
        assert output.status == ExecutionStatus.FAILED
        assert output.error == "Timeout en API externa"
        assert "falló" in output.response or "error" in output.response.lower()

    @pytest.mark.asyncio
    async def test_conclude_node_computes_execution_time_from_request(self) -> None:
        """Verifica cómputo de execution_time_ms usando created_at de la solicitud."""
        past_time = datetime.now(UTC) - timedelta(milliseconds=250)
        req = AgentInput(
            execution_id="exec-time-01",
            thread_id="thread-time-01",
            prompt="Consulta cronometrada",
            created_at=past_time,
        )

        state: AgentState = {
            "request": req,
            "messages": [AIMessage(content="Respuesta rápida")],
        }

        result = await conclude_node(state)
        output = result["output"]
        assert isinstance(output, AgentOutput)
        # Debe ser al menos 200 ms
        assert output.execution_time_ms >= 200.0

    @pytest.mark.asyncio
    async def test_conclude_node_enriches_messages_with_aimessage(self) -> None:
        """Verifica que si no había AIMessage al final, conclude lo genere y añada al historial."""
        state: AgentState = {
            "request": AgentInput(
                execution_id="exec-msg-01",
                thread_id="thread-msg-01",
                prompt="Solo estímulo humano",
            ),
            "messages": [HumanMessage(content="Solo estímulo humano")],
        }

        result = await conclude_node(state)
        messages = result["messages"]
        assert len(messages) >= 2
        assert isinstance(messages[-1], AIMessage)
        assert len(str(messages[-1].content)) > 0

    @pytest.mark.asyncio
    async def test_conclude_node_integrated_in_graph(
        self, sample_registry: CapabilityRegistry
    ) -> None:
        """Verifica que el grafo compilado complete el ciclo y devuelva AgentOutput."""
        builder = GraphBuilder(sample_registry)
        graph = builder.build()

        config: RunnableConfig = {"configurable": {"thread_id": "thread-conclude-int-01"}}
        initial_state: AgentState = {
            "request": AgentInput(
                execution_id="exec-conclude-int-01",
                thread_id="thread-conclude-int-01",
                prompt="Hola agente",
            ),
            "messages": [HumanMessage(content="Hola agente")],
            "status": AgentExecutionStatus.IDLE,
        }

        result = await graph.ainvoke(initial_state, config=config)

        assert result["status"] == AgentExecutionStatus.RESOLVED
        assert result["is_resolved"] is True
        assert "output" in result

        output = result["output"]
        assert isinstance(output, AgentOutput)
        assert output.status == ExecutionStatus.COMPLETED
        assert output.execution_id == "exec-conclude-int-01"
        assert output.thread_id == "thread-conclude-int-01"
        assert output.execution_time_ms >= 0.0

        # Validación del StateSnapshot
        snapshot = await graph.aget_state(config)
        assert snapshot is not None
        assert snapshot.next == ()  # Concluyó en END
        assert "output" in snapshot.values
        snapshot_output = snapshot.values["output"]
        output_status = getattr(snapshot_output, "status", None) or (
            snapshot_output.get("status") if isinstance(snapshot_output, dict) else None
        )
        assert output_status in (ExecutionStatus.COMPLETED, ExecutionStatus.COMPLETED.value)

    @pytest.mark.asyncio
    async def test_conclude_node_filters_meta_evaluation_and_uses_clean_tool_output(self) -> None:
        """Verifica que conclude_node descarte meta-comentarios de auditoría y use la salida textual limpia de la herramienta."""
        state: AgentState = {
            "request": AgentInput(
                execution_id="exec-meta-01",
                thread_id="thread-meta-01",
                prompt="¿Qué tiempo hace en Alcobendas?",
            ),
            "execution_records": [
                StepExecutionRecord(
                    step_id="step-weather",
                    tool_name="get_weather",
                    status=StepStatus.COMPLETED,
                    output="El clima actual en Alcobendas es de 20.0°C con cielo despejado.",
                    duration_ms=45.0,
                )
            ],
            "evaluation_records": [
                EvaluationRecord(
                    goal_status=GoalStatus.SATISFIED,
                    explanation="La respuesta del tool get_weather indica el clima actual en Alcobendas, cumpliendo la solicitud del usuario.",
                    iteration=1,
                    timestamp=datetime.now(UTC),
                )
            ],
            "status": AgentExecutionStatus.EXECUTING,
        }

        result = await conclude_node(state)

        assert result["status"] == AgentExecutionStatus.RESOLVED
        assert result["is_resolved"] is True
        output = result["output"]
        assert isinstance(output, AgentOutput)
        assert output.status == ExecutionStatus.COMPLETED
        # Debe haber descartado el meta-comentario y seleccionado la salida sustantiva del clima
        assert output.response == "El clima actual en Alcobendas es de 20.0°C con cielo despejado."
        assert "La respuesta del tool" not in output.response
