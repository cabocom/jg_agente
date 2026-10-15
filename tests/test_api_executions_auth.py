# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Tests exhaustivos de autenticación HMAC, anti-replay e integridad de petición (GLOBAL-001 / ISSUE-AGENT-001)."""

import hashlib
import json
import time
from collections.abc import Generator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import app
from app.models.registration import AgentCredentials
from app.security.auth import (
    compute_canonical_string,
    compute_hmac_signature,
    verify_hmac_signature,
)

TEST_AGENT_ID = "test-agent-uuid-001"
TEST_SECRET = "super_secret_permanent_key_for_testing_12345"


def create_auth_headers(
    method: str,
    path: str,
    body: str | bytes | dict[str, Any] = "",
    secret: str = TEST_SECRET,
    agent_id: str = TEST_AGENT_ID,
    timestamp: int | None = None,
) -> dict[str, str]:
    """Helper para generar cabeceras de autenticación válidas según el contrato canónico."""
    if timestamp is None:
        timestamp = int(time.time())

    body_bytes = (
        body.encode("utf-8")
        if isinstance(body, str)
        else (json.dumps(body).encode("utf-8") if isinstance(body, dict) else body)
    )

    canonical = compute_canonical_string(
        method=method,
        path=path,
        timestamp=timestamp,
        body_bytes=body_bytes,
    )
    sig = compute_hmac_signature(secret, canonical)

    return {
        "X-Signature": sig,
        "X-Timestamp": str(timestamp),
        "X-Agent-ID": agent_id,
    }


@pytest.fixture(autouse=True)
def setup_agent_auth_context() -> Generator[None, None, None]:
    """Configura credenciales de prueba conocidas en settings y app.state."""
    from app.api.executions import get_agent_graph
    from app.core.checkpointer import get_memory_checkpointer
    from app.core.graph import GraphBuilder
    from app.core.llm import MockChatModel
    from app.core.registry import CapabilityRegistry
    from app.security.guard import SecurityGuard

    orig_agent_id = settings.AGENT_ID
    orig_secret = settings.PERMANENT_AGENT_SECRET

    settings.AGENT_ID = TEST_AGENT_ID
    settings.PERMANENT_AGENT_SECRET = TEST_SECRET

    app.state.credentials = AgentCredentials(
        agent_id=TEST_AGENT_ID,
        permanent_secret=TEST_SECRET,
        agent_name="Test Agent",
        verified=True,
    )

    mock_graph = GraphBuilder(
        registry=CapabilityRegistry(),
        llm=MockChatModel(response_content="Auth test response"),
        security_guard=SecurityGuard(),
    ).build(checkpointer=get_memory_checkpointer())

    app.dependency_overrides[get_agent_graph] = lambda: mock_graph

    yield

    app.dependency_overrides.pop(get_agent_graph, None)
    settings.AGENT_ID = orig_agent_id
    settings.PERMANENT_AGENT_SECRET = orig_secret


# ==============================================================================
# 1. Tests Unitarios del Contrato Criptográfico Canónico
# ==============================================================================


def test_canonical_string_format() -> None:
    """Valida el formato exacto del string canónico: METHOD\\nPATH\\nTIMESTAMP\\nBODY_SHA256."""
    body = b'{"prompt": "hola"}'
    expected_hash = hashlib.sha256(body).hexdigest()
    canonical = compute_canonical_string("post", "/executions/trigger", 1725990000, body)

    expected = f"POST\n/executions/trigger\n1725990000\n{expected_hash}"
    assert canonical == expected


def test_canonical_string_empty_body() -> None:
    """Valida el hash para cuerpos vacíos (ej. peticiones GET)."""
    empty_hash = hashlib.sha256(b"").hexdigest()
    canonical = compute_canonical_string("GET", "/executions/thread-123", "1725990000", b"")
    assert canonical == f"GET\n/executions/thread-123\n1725990000\n{empty_hash}"


def test_verify_hmac_signature_matching_and_failing() -> None:
    """Valida verificación en tiempo constante y rechazo de firmas erróneas."""
    canonical = "POST\n/executions/trigger\n1725990000\ne3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    sig = compute_hmac_signature("secret_key", canonical)

    assert verify_hmac_signature("secret_key", canonical, sig) is True
    assert verify_hmac_signature("wrong_secret", canonical, sig) is False
    assert verify_hmac_signature("secret_key", canonical, "deadbeef" + sig[8:]) is False


# ==============================================================================
# 2. Tests de Integración HTTP contra los Endpoints de /executions
# ==============================================================================


@pytest.mark.asyncio
async def test_missing_all_headers_returns_401() -> None:
    """Una petición sin cabeceras de autenticación debe ser rechazada con HTTP 401."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post("/executions/trigger", json={"prompt": "test"})
        assert resp.status_code == 401
        assert "Cabeceras de autenticación requeridas ausentes" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_missing_single_header_returns_401() -> None:
    """Omitir cualquiera de las tres cabeceras requeridas produce 401."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        headers = create_auth_headers("POST", "/executions/trigger", body='{"prompt": "test"}')

        # Quitar X-Signature
        h_no_sig = {k: v for k, v in headers.items() if k != "X-Signature"}
        resp = await ac.post("/executions/trigger", json={"prompt": "test"}, headers=h_no_sig)
        assert resp.status_code == 401
        assert "X-Signature" in resp.json()["detail"]

        # Quitar X-Timestamp
        h_no_ts = {k: v for k, v in headers.items() if k != "X-Timestamp"}
        resp = await ac.post("/executions/trigger", json={"prompt": "test"}, headers=h_no_ts)
        assert resp.status_code == 401
        assert "X-Timestamp" in resp.json()["detail"]

        # Quitar X-Agent-ID
        h_no_id = {k: v for k, v in headers.items() if k != "X-Agent-ID"}
        resp = await ac.post("/executions/trigger", json={"prompt": "test"}, headers=h_no_id)
        assert resp.status_code == 401
        assert "X-Agent-ID" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_expired_timestamp_anti_replay_returns_401() -> None:
    """Peticiones con timestamp fuera de la ventana de 300 segundos son rechazadas."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        old_time = int(time.time()) - 305  # 5 minutos y 5 segundos atrás
        headers = create_auth_headers(
            "POST", "/executions/trigger", body='{"prompt": "test"}', timestamp=old_time
        )
        resp = await ac.post("/executions/trigger", json={"prompt": "test"}, headers=headers)
        assert resp.status_code == 401
        assert "anti-replay" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_future_timestamp_skew_returns_401() -> None:
    """Peticiones con timestamp adelantado en el futuro (> 300s) son rechazadas."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        future_time = int(time.time()) + 310
        headers = create_auth_headers(
            "POST", "/executions/trigger", body='{"prompt": "test"}', timestamp=future_time
        )
        resp = await ac.post("/executions/trigger", json={"prompt": "test"}, headers=headers)
        assert resp.status_code == 401
        assert "anti-replay" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_agent_id_mismatch_returns_401() -> None:
    """Peticiones dirigidas a otro agent_id son rechazadas con 401."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        headers = create_auth_headers(
            "POST",
            "/executions/trigger",
            body='{"prompt": "test"}',
            agent_id="wrong-agent-id-999",
        )
        resp = await ac.post("/executions/trigger", json={"prompt": "test"}, headers=headers)
        assert resp.status_code == 401
        assert "no coincide" in resp.json()["detail"].lower()


# ==============================================================================
# 3. Pruebas de Manipulación (Tampering)
# ==============================================================================


@pytest.mark.asyncio
async def test_tampering_single_byte_in_body_fails_with_401() -> None:
    """Modificar un solo byte en el cuerpo JSON invalida la firma criptográfica."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        original_body = '{"execution_id": "e1", "thread_id": "t1", "prompt": "hola mundo"}'
        headers = create_auth_headers("POST", "/executions/trigger", body=original_body)

        # Alteramos un único carácter en el payload enviado ("hola mundo" -> "hola mundx")
        tampered_body = '{"execution_id": "e1", "thread_id": "t1", "prompt": "hola mundx"}'

        resp = await ac.post(
            "/executions/trigger",
            content=tampered_body,
            headers={**headers, "Content-Type": "application/json"},
        )
        assert resp.status_code == 401
        assert (
            "inválida" in resp.json()["detail"].lower()
            or "alterado" in resp.json()["detail"].lower()
        )


@pytest.mark.asyncio
async def test_tampering_path_fails_with_401() -> None:
    """Una firma generada para una ruta no puede reutilizarse en otra ruta."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Firmamos para /executions/trigger
        headers = create_auth_headers("GET", "/executions/trigger", body=b"")

        # Enviamos a /executions/thread-123
        resp = await ac.get("/executions/thread-123", headers=headers)
        assert resp.status_code == 401
        assert (
            "inválida" in resp.json()["detail"].lower()
            or "alterado" in resp.json()["detail"].lower()
        )


@pytest.mark.asyncio
async def test_tampering_method_fails_with_401() -> None:
    """Una firma generada para POST falla si se invoca con GET."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Firmamos como GET
        headers = create_auth_headers("GET", "/executions/trigger", body=b"")

        # Enviamos como POST
        resp = await ac.post("/executions/trigger", json={"prompt": "hi"}, headers=headers)
        assert resp.status_code == 401
        assert (
            "inválida" in resp.json()["detail"].lower()
            or "alterado" in resp.json()["detail"].lower()
        )


@pytest.mark.asyncio
async def test_valid_request_passes_authentication() -> None:
    """Petición con firma correcta, timestamp fresco y agent_id exacto supera la barrera de autenticación."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        payload = {
            "execution_id": "exec-auth-test-01",
            "thread_id": "thread-auth-test-01",
            "prompt": "hola test",
        }
        body_str = json.dumps(payload)
        headers = create_auth_headers("POST", "/executions/trigger", body=body_str)

        resp = await ac.post(
            "/executions/trigger",
            content=body_str,
            headers={**headers, "Content-Type": "application/json"},
        )
        # La autenticación pasa (código 200 OK)
        assert resp.status_code == 200
        data = resp.json()
        assert data["execution_id"] == "exec-auth-test-01"
        assert data["thread_id"] == "thread-auth-test-01"


@pytest.mark.asyncio
async def test_nonce_replay_is_rejected_with_401() -> None:
    """Gap 6: una petición con el mismo X-Nonce reutilizado dentro de la ventana recibe 401."""
    from app.security.auth import get_nonce_cache

    get_nonce_cache().clear()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        payload = {
            "execution_id": "exec-nonce-01",
            "thread_id": "thread-nonce-01",
            "prompt": "test",
        }
        body_str = json.dumps(payload)
        now_ts = int(time.time())
        nonce = "test-uuid-nonce-12345678"

        canonical = compute_canonical_string(
            "POST", "/executions/trigger", now_ts, body_str.encode("utf-8"), nonce=nonce
        )
        sig = compute_hmac_signature(TEST_SECRET, canonical)

        headers = {
            "X-Signature": sig,
            "X-Timestamp": str(now_ts),
            "X-Agent-ID": TEST_AGENT_ID,
            "X-Nonce": nonce,
            "Content-Type": "application/json",
        }

        # 1. Primera petición: 200 OK
        resp1 = await ac.post("/executions/trigger", content=body_str, headers=headers)
        assert resp1.status_code == 200

        # 2. Petición repetida exactamente igual (replay attack con mismo nonce y timestamp): 401
        resp2 = await ac.post("/executions/trigger", content=body_str, headers=headers)
        assert resp2.status_code == 401
        assert "nonce replayed" in resp2.json()["detail"].lower()
