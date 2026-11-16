# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Pruebas para los endpoints base de FastAPI y verificación de salud."""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> TestClient:
    """Cliente síncrono de pruebas para FastAPI."""
    return TestClient(app)


def test_root_endpoint(client: TestClient) -> None:
    """Verifica que el endpoint raíz responda con metadatos del servicio."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "jg_agente"
    assert data["version"] == "2.0.0"
    assert data["status"] == "online"


def test_health_endpoint_structure(client: TestClient) -> None:
    """Verifica la estructura y respuesta del endpoint /health."""
    response = client.get("/health")
    # En entorno local sin PostgreSQL local arrancado en host, puede ser 200 o 503 pero debe tener estructura válida
    assert response.status_code in (200, 503)
    data = response.json()
    assert "status" in data
    assert "service" in data
    assert "database" in data
    assert data["service"] == "jg_agente"
