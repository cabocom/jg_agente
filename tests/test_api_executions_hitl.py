# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Tests de integración para los endpoints de resolución HITL POST /approve y /reject."""

from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver

from app.api.executions import get_agent_graph
from app.core.graph import GraphBuilder
from app.core.llm import MockChatModel
from app.core.registry import CapabilityRegistry
from app.main import app
from app.models.io import ExecutionStatus
from app.models.tools import AgentTool, RiskLevel
from app.security.guard import SecurityGuard


@pytest.fixture
def executed_tools() -> list[str]:
    """Lista acumuladora para registrar invocaciones de herramientas."""
    return []


@pytest.fixture
def hitl_registry(executed_tools: list[str]) -> CapabilityRegistry:
    """Registry con herramienta de diagnóstico de bajo riesgo y herramienta destructiva de alto riesgo."""
    reg = CapabilityRegistry()

    def safe_query(param: str = "ok") -> str:
        executed_tools.append(f"safe_query:{param}")
        return f"safe_result:{param}"

    def dangerous_purge(target: str) -> str:
        executed_tools.append(f"dangerous_purge:{target}")
        return f"purged:{target}"

    reg.register_tool(
        AgentTool(
            name="safe_query",
            description="Herramienta segura de lectura",
            func=safe_query,
            risk_level=RiskLevel.LOW,
            category="diagnostic",
        )
    )
    reg.register_tool(
        AgentTool(
            name="dangerous_purge",
            description="Herramienta crítica de borrado masivo",
            func=dangerous_purge,
            risk_level=RiskLevel.CRITICAL,
            category="ops",
        )
    )
    return reg


@pytest.fixture
def shared_checkpointer() -> MemorySaver:
    """Checkpointer persistente en memoria compartido entre pausa y reanudación."""
    return MemorySaver()


def make_hitl_graph(
    registry: CapabilityRegistry, checkpointer: MemorySaver, llm: MockChatModel
) -> Any:
    builder = GraphBuilder(
        registry=registry,
        llm=llm,
        security_guard=SecurityGuard(),
    )
    return builder.build(checkpointer=checkpointer)


@pytest.fixture
def client(
    hitl_registry: CapabilityRegistry, shared_checkpointer: MemorySaver
) -> Generator[TestClient, None, None]:
    """TestClient configurado para pruebas HITL."""
    llm = MockChatModel(
        tool_calls_to_return=[
            {
                "id": "call_purge_01",
                "name": "dangerous_purge",
                "args": {"target": "database-cluster"},
                "type": "tool_call",
            }
        ]
    )
    graph = make_hitl_graph(hitl_registry, shared_checkpointer, llm)
    app.dependency_overrides[get_agent_graph] = lambda: graph

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def test_approve_thread_not_found(client: TestClient) -> None:
    """Valida que intentar aprobar un thread_id inexistente devuelve HTTP 404 Not Found."""
    response = client.post("/executions/thread-inexistente-404/approve", json={"approver": "alice"})
    assert response.status_code == 404
    data = response.json()
    assert "no encontrado" in data["detail"].lower()


def test_reject_thread_not_found(client: TestClient) -> None:
    """Valida que intentar rechazar un thread_id inexistente devuelve HTTP 404 Not Found."""
    response = client.post("/executions/thread-inexistente-404/reject", json={"approver": "bob"})
    assert response.status_code == 404
    data = response.json()
    assert "no encontrado" in data["detail"].lower()


def test_approve_already_completed_thread_conflict(
    client: TestClient, hitl_registry: CapabilityRegistry, shared_checkpointer: MemorySaver
) -> None:
    """Valida que intentar aprobar un thread_id ya concluido devuelve HTTP 409 Conflict."""
    thread_id = "thread-completed-no-hitl"
    # Grafo sin herramientas de riesgo (responde directamente sin pausar)
    safe_llm = MockChatModel(response_content="Respuesta sin herramientas.")
    graph = make_hitl_graph(hitl_registry, shared_checkpointer, safe_llm)
    app.dependency_overrides[get_agent_graph] = lambda: graph

    # Disparar ejecución completada
    trigger_resp = client.post(
        "/executions/trigger",
        json={"execution_id": "exec-safe-01", "thread_id": thread_id, "prompt": "Hola"},
    )
    assert trigger_resp.status_code == 200
    assert trigger_resp.json()["status"] == ExecutionStatus.COMPLETED.value

    # Intentar aprobar hilo ya completado
    approve_resp = client.post(f"/executions/{thread_id}/approve", json={"approver": "alice"})
    assert approve_resp.status_code == 409
    assert "ya ha finalizado" in approve_resp.json()["detail"].lower()


def test_hitl_approve_flow_success(client: TestClient, executed_tools: list[str]) -> None:
    """Valida flujo HITL completo: pausa -> POST /{thread_id}/approve -> ejecución exitosa (200 completed)."""
    thread_id = "thread-hitl-flow-approve-01"
    executed_tools.clear()

    # 1. Disparar ejecución con herramienta de riesgo -> debe pausarse
    trigger_payload = {
        "execution_id": "exec-hitl-appr-01",
        "thread_id": thread_id,
        "prompt": "Purgar base de datos",
    }
    trigger_resp = client.post("/executions/trigger", json=trigger_payload)
    assert trigger_resp.status_code == 200
    trig_data = trigger_resp.json()
    assert trig_data["status"] == ExecutionStatus.WAITING_APPROVAL.value
    assert trig_data["requires_approval"] is True
    assert trig_data["pending_approval_id"] == "human_approval_required"

    # Verificar que la herramienta peligrosa AÚN NO se ha ejecutado
    assert len(executed_tools) == 0

    # 2. Enviar aprobación vía POST /{thread_id}/approve
    approve_payload = {
        "approver": "secops_director",
        "notes": "Aprobado para ventana de medianoche",
    }
    appr_resp = client.post(f"/executions/{thread_id}/approve", json=approve_payload)
    assert appr_resp.status_code == 200

    appr_data = appr_resp.json()
    assert appr_data["execution_id"] == "exec-hitl-appr-01"
    assert appr_data["thread_id"] == thread_id
    assert appr_data["status"] == ExecutionStatus.COMPLETED.value
    assert appr_data["requires_approval"] is False
    assert appr_data["pending_approval_id"] is None

    # Verificar que la herramienta peligrosa SÍ se ejecutó tras la aprobación
    assert len(executed_tools) == 1
    assert "dangerous_purge:database-cluster" in executed_tools[0]


def test_hitl_reject_flow_cancels(client: TestClient, executed_tools: list[str]) -> None:
    """Valida flujo HITL completo: pausa -> POST /{thread_id}/reject -> cancelación (200 cancelled)."""
    thread_id = "thread-hitl-flow-reject-01"
    executed_tools.clear()

    # 1. Disparar ejecución con herramienta de riesgo -> debe pausarse
    trigger_payload = {
        "execution_id": "exec-hitl-rej-01",
        "thread_id": thread_id,
        "prompt": "Purgar base de datos",
    }
    trigger_resp = client.post("/executions/trigger", json=trigger_payload)
    assert trigger_resp.status_code == 200
    assert trigger_resp.json()["status"] == ExecutionStatus.WAITING_APPROVAL.value

    # 2. Enviar rechazo vía POST /{thread_id}/reject
    reject_payload = {
        "approver": "lead_architect",
        "notes": "Operación cancelada por alto riesgo no justificado",
    }
    rej_resp = client.post(f"/executions/{thread_id}/reject", json=reject_payload)
    assert rej_resp.status_code == 200

    rej_data = rej_resp.json()
    assert rej_data["execution_id"] == "exec-hitl-rej-01"
    assert rej_data["thread_id"] == thread_id
    assert rej_data["status"] == ExecutionStatus.CANCELLED.value
    assert rej_data["requires_approval"] is False
    assert rej_data["pending_approval_id"] is None
    assert (
        "cancelada" in rej_data["response"].lower() or "alto riesgo" in rej_data["response"].lower()
    )

    # Verificar que la herramienta peligrosa NUNCA se ejecutó
    assert len(executed_tools) == 0


def test_hitl_endpoints_with_body_thread_id(
    client: TestClient, hitl_registry: CapabilityRegistry
) -> None:
    """Valida rutas POST /executions/approve y POST /executions/reject con thread_id en payload."""
    # Validación 422 si falta thread_id en body
    resp_422 = client.post("/executions/approve", json={"approver": "admin"})
    assert resp_422.status_code == 422

    resp_rej_422 = client.post("/executions/reject", json={"approver": "admin"})
    assert resp_rej_422.status_code == 422

    # Probar approve con thread_id en body
    thread_id = "thread-body-hitl-01"
    trigger_resp = client.post(
        "/executions/trigger",
        json={"execution_id": "exec-body-01", "thread_id": thread_id, "prompt": "Purgar"},
    )
    assert trigger_resp.status_code == 200
    assert trigger_resp.json()["status"] == ExecutionStatus.WAITING_APPROVAL.value

    appr_resp = client.post(
        "/executions/approve",
        json={"thread_id": thread_id, "approver": "ops_user", "notes": "OK desde body"},
    )
    assert appr_resp.status_code == 200
    assert appr_resp.json()["status"] == ExecutionStatus.COMPLETED.value
