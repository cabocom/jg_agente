"""Tests unitarios e integrados para el nodo base reason y el subsistema LLM."""

from typing import Any

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from app.core.graph import GraphBuilder
from app.core.llm import MockChatModel, get_chat_model
from app.core.registry import CapabilityRegistry
from app.models.io import AgentInput
from app.models.state import (
    AgentExecutionStatus,
    AgentState,
    IntentModel,
)
from app.models.tools import AgentTool, RiskLevel, ToolResult
from app.nodes.reason import reason_node


def dummy_weather_tool(location: str = "Madrid") -> ToolResult:
    return ToolResult(success=True, output=f"Soleado en {location}, 22C")


# ==========================================================
# 1. Pruebas Unitarias del Proveedor LLM (MockChatModel)
# ==========================================================


class TestMockChatModel:
    """Pruebas para el modelo simulado y factoría LLM."""

    def test_mock_chat_model_direct_response(self) -> None:
        model = MockChatModel(response_content="Respuesta simulada directa")
        res = model.invoke([HumanMessage(content="Hola")])
        assert isinstance(res, AIMessage)
        assert res.content == "Respuesta simulada directa"
        assert res.tool_calls == []

    def test_mock_chat_model_explicit_tool_calls(self) -> None:
        expected_calls = [
            {
                "id": "call_1",
                "name": "get_weather",
                "args": {"location": "Sevilla"},
                "type": "tool_call",
            }
        ]
        model = MockChatModel(tool_calls_to_return=expected_calls)
        res = model.invoke([HumanMessage(content="¿Qué tiempo hace en Sevilla?")])
        assert isinstance(res, AIMessage)
        assert res.tool_calls == expected_calls

    def test_get_chat_model_factory(self) -> None:
        mock_model = get_chat_model(provider="mock")
        assert isinstance(mock_model, MockChatModel)


# ==========================================================
# 2. Pruebas Unitarias del Nodo reason
# ==========================================================


class TestReasonNode:
    """Pruebas del nodo cognitivo reason de LangGraph."""

    @pytest.mark.asyncio
    async def test_reason_node_direct_response(self) -> None:
        """Verifica que el nodo genera respuesta directa e intent conclude sin invocar tools."""
        registry = CapabilityRegistry()
        llm = MockChatModel(
            response_content="Hola, ¿en qué puedo ayudarte hoy?",
            auto_tool_calls=False,
        )

        initial_state: AgentState = {
            "request": AgentInput(
                execution_id="exec-reason-01",
                thread_id="th-reason-01",
                prompt="Hola, ¿cómo estás?",
            ),
            "messages": [],
            "status": AgentExecutionStatus.IDLE,
        }

        output = await reason_node(
            state=initial_state,
            registry=registry,
            llm=llm,
        )

        assert output["status"] == AgentExecutionStatus.REASONING
        assert len(output["messages"]) == 1
        ai_msg = output["messages"][0]
        assert isinstance(ai_msg, AIMessage)
        assert ai_msg.content == "Hola, ¿en qué puedo ayudarte hoy?"
        assert ai_msg.tool_calls == []

        intent = output["intent"]
        assert isinstance(intent, IntentModel)
        assert intent.action_type == "conclude"
        assert intent.parameters["response"] == "Hola, ¿en qué puedo ayudarte hoy?"

        # Auditoría
        assert len(output["audit_trail"]) == 1
        assert output["audit_trail"][0].event_type == "reasoning_completed"
        assert output["audit_trail"][0].details["action_type"] == "conclude"

    @pytest.mark.asyncio
    async def test_reason_node_generates_tool_calls(self) -> None:
        """Verifica que el nodo genera lista de tool_calls e intent act cuando el LLM lo solicita."""
        registry = CapabilityRegistry()
        weather_tool = AgentTool(
            name="get_weather",
            description="Obtiene la previsión meteorológica",
            category="weather",
            func=dummy_weather_tool,
            risk_level=RiskLevel.LOW,
        )
        registry.register_tool(weather_tool)

        tool_calls = [
            {
                "id": "call_weather_01",
                "name": "get_weather",
                "args": {"location": "Valencia"},
                "type": "tool_call",
            }
        ]
        llm = MockChatModel(tool_calls_to_return=tool_calls)

        initial_state: AgentState = {
            "request": AgentInput(
                execution_id="exec-reason-02",
                thread_id="th-reason-02",
                prompt="Consulta el tiempo en Valencia",
            ),
            "messages": [],
            "status": AgentExecutionStatus.IDLE,
        }

        output = await reason_node(
            state=initial_state,
            registry=registry,
            llm=llm,
        )

        assert output["status"] == AgentExecutionStatus.REASONING
        assert len(output["messages"]) == 1
        ai_msg = output["messages"][0]
        assert isinstance(ai_msg, AIMessage)
        assert len(ai_msg.tool_calls) == 1
        assert ai_msg.tool_calls[0]["name"] == "get_weather"
        assert ai_msg.tool_calls[0]["args"] == {"location": "Valencia"}

        intent = output["intent"]
        assert isinstance(intent, IntentModel)
        assert intent.action_type == "act"
        assert "tool_calls" in intent.parameters
        assert intent.parameters["tool_calls"] == tool_calls

        # Auditoría
        assert len(output["audit_trail"]) == 1
        assert output["audit_trail"][0].event_type == "reasoning_completed"
        assert output["audit_trail"][0].details["action_type"] == "act"
        assert output["audit_trail"][0].details["tools"] == ["get_weather"]

    @pytest.mark.asyncio
    async def test_reason_node_with_conversational_memory(self) -> None:
        """Verifica que el nodo respeta y procesa el historial multi-turno previo."""
        registry = CapabilityRegistry()
        llm = MockChatModel(response_content="Entendido, procediendo con el siguiente paso.")

        history: list[BaseMessage] = [
            SystemMessage(content="Sistema preconfigurado"),
            HumanMessage(content="Paso 1: Validar"),
            AIMessage(content="Paso 1 completado con éxito."),
        ]

        state_with_history: AgentState = {
            "request": AgentInput(
                execution_id="exec-reason-03",
                thread_id="th-reason-03",
                prompt="Paso 2: Continuar",
            ),
            "messages": history,
            "status": AgentExecutionStatus.IDLE,
        }

        output = await reason_node(
            state=state_with_history,
            registry=registry,
            llm=llm,
        )

        assert output["status"] == AgentExecutionStatus.REASONING
        # Debe emitir el nuevo AIMessage para ser concatenado por add_messages
        assert len(output["messages"]) == 1
        assert output["messages"][0].content == "Entendido, procediendo con el siguiente paso."

    @pytest.mark.asyncio
    async def test_reason_node_auto_detection_of_tools(self) -> None:
        """Verifica que el MockChatModel auto-detecta la tool si coincide con el prompt."""
        registry = CapabilityRegistry()
        weather_tool = AgentTool(
            name="get_weather",
            description="Obtiene la previsión meteorológica",
            category="weather",
            func=dummy_weather_tool,
            risk_level=RiskLevel.LOW,
        )
        registry.register_tool(weather_tool)

        llm = MockChatModel(auto_tool_calls=True)

        initial_state: AgentState = {
            "request": AgentInput(
                execution_id="exec-reason-04",
                thread_id="th-reason-04",
                prompt="Por favor invoca get_weather para ver las condiciones",
            ),
            "messages": [],
            "status": AgentExecutionStatus.IDLE,
        }

        output = await reason_node(
            state=initial_state,
            registry=registry,
            llm=llm,
        )

        ai_msg = output["messages"][0]
        assert len(ai_msg.tool_calls) == 1
        assert ai_msg.tool_calls[0]["name"] == "get_weather"
        assert output["intent"].action_type == "act"


# ==========================================================
# 3. Integración de reason_node con GraphBuilder
# ==========================================================


class TestReasonNodeInGraphBuilder:
    """Pruebas de integración del nodo reason dentro del grafo compilado."""

    @pytest.mark.asyncio
    async def test_graph_with_reason_direct_response_routes_to_conclude(self) -> None:
        """Grafo que recibe una consulta directa y concluye sin ejecutar herramientas."""
        registry = CapabilityRegistry()
        llm = MockChatModel(response_content="Respuesta final directa sin herramientas.")

        builder = GraphBuilder(registry, llm=llm)
        graph = builder.build()

        config: RunnableConfig = {"configurable": {"thread_id": "th-graph-reason-direct"}}
        initial_messages: list[BaseMessage] = [HumanMessage(content="Hola agente")]
        initial_state: AgentState = {
            "request": AgentInput(
                execution_id="exec-gr-01",
                thread_id="th-graph-reason-direct",
                prompt="Hola agente",
            ),
            "messages": initial_messages,
            "status": AgentExecutionStatus.IDLE,
        }

        result = await graph.ainvoke(initial_state, config=config)

        assert result["status"] == AgentExecutionStatus.RESOLVED
        assert result["is_resolved"] is True
        assert result["intent"].action_type == "conclude"
        # Comprobar que messages contiene el AIMessage generado por reason
        ai_messages = [m for m in result["messages"] if isinstance(m, AIMessage)]
        assert len(ai_messages) >= 1
        assert "Respuesta final directa" in ai_messages[0].content

    @pytest.mark.asyncio
    async def test_capabilities_inquiry_routes_to_conclude_even_with_planner(self) -> None:
        """Verifica que consultas sobre capacidades concluyen directamente sin saltar al planificador."""
        from app.plugins.base import PlannerEngine

        class DummyPlanner(PlannerEngine):
            name: str = "test_planner"
            engine_type: str = "planner"

            def create_plan(self, state: Any = None) -> Any:
                raise AssertionError(
                    "El planificador NO debe ser invocado para consultas de capacidades."
                )

        registry = CapabilityRegistry()
        registry.register_engine(DummyPlanner())

        llm = MockChatModel(
            response_content="Soy un agente inteligente. Mis capacidades incluyen gestión de contenedores Docker.",
            auto_tool_calls=False,
        )

        state: AgentState = {
            "request": AgentInput(
                execution_id="exec-cap-01",
                thread_id="th-cap-01",
                prompt="dime que capacidades tienes",
            ),
            "messages": [],
            "status": AgentExecutionStatus.IDLE,
        }

        output = await reason_node(state=state, registry=registry, llm=llm)

        assert output["status"] == AgentExecutionStatus.REASONING
        assert output["intent"].action_type == "conclude"
        assert "capacidades" in str(output["intent"].parameters.get("response"))

        # Validar en grafo compilado completo
        builder = GraphBuilder(registry, llm=llm)
        graph = builder.build()
        config: RunnableConfig = {"configurable": {"thread_id": "th-cap-graph"}}
        res = await graph.ainvoke(state, config=config)

        assert res["status"] == AgentExecutionStatus.RESOLVED
        assert res["is_resolved"] is True
        assert res["intent"].action_type == "conclude"
        assert res.get("plan") is None


class TestReasonNodeIntentClassification:
    """Pruebas para la determinación semántica mediante IA de saludos vs peticiones de acción (AGENTE-LOGIC-01)."""

    @pytest.mark.asyncio
    async def test_llm_distinguishes_greeting_from_operational_query(self) -> None:
        """Verifica que un saludo simple concluye pero una consulta como 'Dime el estado...' deriva al planificador."""
        from app.models.state import ExecutionPlan
        from app.plugins.base import PlannerEngine

        class DummyPlanner(PlannerEngine):
            @property
            def name(self) -> str:
                return "mock_dag_planner"

            async def startup(self) -> None:
                pass

            async def shutdown(self) -> None:
                pass

            def create_plan(self, state: Any = None) -> Any:
                return ExecutionPlan(plan_id="p1", goal="planificado", steps=[])

        registry = CapabilityRegistry()
        planner = DummyPlanner()
        registry.register_engine(planner)

        llm = MockChatModel(auto_tool_calls=False)

        # 1. Saludo puro -> debe concluir directamente
        greeting_state: AgentState = {
            "request": AgentInput(
                execution_id="exec-greet",
                thread_id="th-greet",
                prompt="Hola, buenos días",
            ),
            "messages": [],
            "status": AgentExecutionStatus.IDLE,
        }
        res_greet = await reason_node(state=greeting_state, registry=registry, llm=llm)
        assert res_greet["intent"].action_type == "conclude"

        # 2. Consultas operativas con prefijos en español -> la IA las clasifica como ACTION y deriva a plan
        operational_queries = [
            "Dime el estado de los contenedores",
            "¿Cuál es el uso de memoria de los pods?",
            "Explica los errores en los logs del servicio auth",
            "Cuenta cuántos servicios están caídos",
        ]
        for query in operational_queries:
            op_state: AgentState = {
                "request": AgentInput(
                    execution_id="exec-op",
                    thread_id="th-op",
                    prompt=query,
                ),
                "messages": [],
                "status": AgentExecutionStatus.IDLE,
            }
            res_op = await reason_node(state=op_state, registry=registry, llm=llm)
            assert res_op["intent"].action_type == "plan", (
                f"La consulta '{query}' debió derivar a plan, no a conclude"
            )
            assert res_op["intent"].parameters["planner"] == "mock_dag_planner"
