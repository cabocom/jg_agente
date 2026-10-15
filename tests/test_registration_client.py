# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez <contacto@javiergalvez.com>
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Pruebas unitarias y de integración para el cliente de registro con bootstrap token."""

import os
import stat
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
import pytest

from app.core.config import Settings
from app.core.registration import (
    CredentialStore,
    DashboardConnectionError,
    DashboardRegistrationClient,
    RegistrationAuthError,
    RegistrationConflictError,
    RegistrationError,
    auto_register_agent,
    reload_credentials,
)
from app.core.registry import CapabilityRegistry
from app.models.registration import AgentCredentials

# --- Fixtures ---


@pytest.fixture
def temp_credentials_file(tmp_path: Path) -> Path:
    """Proporciona una ruta temporal segura para el archivo de credenciales."""
    return tmp_path / "test_agent_credentials.json"


@pytest.fixture
def sample_credentials() -> AgentCredentials:
    """Credenciales de prueba para persistencia."""
    return AgentCredentials(
        agent_id="550e8400-e29b-41d4-a716-446655440000",
        permanent_secret="sec_permanent_test_abc123xyz789",
        agent_name="Agent Test Core",
        dashboard_url="http://test-dashboard:8080",
        registered_at="2026-09-05T20:00:00Z",
    )


# --- Tests para CredentialStore ---


def test_credential_store_save_and_load(
    temp_credentials_file: Path, sample_credentials: AgentCredentials
) -> None:
    """Valida la persistencia y lectura de credenciales con permisos 0600 en POSIX."""
    assert not CredentialStore.exists(temp_credentials_file)

    # Guardar
    CredentialStore.save(sample_credentials, temp_credentials_file)
    assert CredentialStore.exists(temp_credentials_file)

    # Validar permisos en sistemas POSIX
    if os.name == "posix":
        file_stat = temp_credentials_file.stat()
        file_mode = stat.S_IMODE(file_stat.st_mode)
        assert file_mode == 0o600

    # Cargar y verificar integridad
    loaded = CredentialStore.load(temp_credentials_file)
    assert loaded is not None
    assert loaded.agent_id == sample_credentials.agent_id
    assert loaded.permanent_secret == sample_credentials.permanent_secret
    assert loaded.agent_name == sample_credentials.agent_name
    assert loaded.dashboard_url == sample_credentials.dashboard_url
    assert loaded.registered_at == sample_credentials.registered_at


def test_credential_store_save_atomic_fsync_and_replace(
    temp_credentials_file: Path, sample_credentials: AgentCredentials
) -> None:
    """Valida que save() escribe en .tmp, ejecuta os.fsync y os.replace atómico."""
    fsync_called = False
    replace_called = False
    real_fsync = os.fsync
    real_replace = os.replace

    def spy_fsync(fd: int) -> None:
        nonlocal fsync_called
        fsync_called = True
        real_fsync(fd)

    def spy_replace(src: Path | str, dst: Path | str) -> None:
        nonlocal replace_called
        replace_called = True
        tmp_path = Path(src)
        assert tmp_path.name.endswith(".tmp")
        assert tmp_path.exists()
        real_replace(src, dst)

    with (
        patch("os.fsync", side_effect=spy_fsync),
        patch("os.replace", side_effect=spy_replace),
    ):
        CredentialStore.save(sample_credentials, temp_credentials_file)

    assert fsync_called is True
    assert replace_called is True
    assert CredentialStore.exists(temp_credentials_file)
    tmp_file = temp_credentials_file.with_name(f"{temp_credentials_file.name}.tmp")
    assert not tmp_file.exists()


def test_credential_store_save_atomic_failure_cleanup(
    temp_credentials_file: Path, sample_credentials: AgentCredentials
) -> None:
    """Valida que si ocurre un fallo durante la escritura, el .tmp se limpia y el target previo no se corrompe."""
    # Pre-crear credencial previa válida
    CredentialStore.save(sample_credentials, temp_credentials_file)
    original_content = temp_credentials_file.read_text(encoding="utf-8")

    tmp_file = temp_credentials_file.with_name(f"{temp_credentials_file.name}.tmp")

    with (
        patch("os.fsync", side_effect=OSError("Disk I/O error simulated")),
        pytest.raises(OSError, match="Disk I/O error simulated"),
    ):
        updated_creds = AgentCredentials(
            agent_id="new-agent",
            permanent_secret="new-secret",
            agent_name="New Agent",
            dashboard_url="http://new-dashboard:8080",
        )
        CredentialStore.save(updated_creds, temp_credentials_file)

    # El archivo temporal debe haberse limpiado
    assert not tmp_file.exists()
    # El archivo previo no debe haberse truncado ni corrompido
    assert temp_credentials_file.read_text(encoding="utf-8") == original_content


def test_credential_store_missing_or_corrupted(temp_credentials_file: Path) -> None:
    """Valida que la lectura de un archivo inexistente o corrupto devuelva None sin lanzar excepciones."""
    # Inexistente
    assert CredentialStore.load(temp_credentials_file) is None

    # Corrupto
    temp_credentials_file.write_text("{ malformed_json: true, ", encoding="utf-8")
    assert CredentialStore.load(temp_credentials_file) is None

    # Vacío
    temp_credentials_file.write_text("   \n", encoding="utf-8")
    assert CredentialStore.load(temp_credentials_file) is None

    # Borrado
    CredentialStore.clear(temp_credentials_file)
    assert not CredentialStore.exists(temp_credentials_file)


# --- Tests para DashboardRegistrationClient ---


@pytest.mark.asyncio
async def test_dashboard_registration_success() -> None:
    """Valida registro exitoso con código 200 y retorno de credenciales permanentes."""
    captured_request: dict[str, Any] = {}

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        captured_request["url"] = str(request.url)
        captured_request["headers"] = dict(request.headers)
        captured_request["body"] = request.read().decode("utf-8")

        return httpx.Response(
            200,
            json={
                "message": "Agente aprovisionado y activado exitosamente",
                "agent_id": "agent-uuid-12345",
                "name": "DevOps SRE Agent",
                "status": "ACTIVE",
                "permanent_secret": "perm_secret_val_999",
                "registered_at": "2026-09-05T20:10:00Z",
            },
        )

    transport = httpx.MockTransport(mock_handler)
    client = DashboardRegistrationClient(
        dashboard_url="http://test-dashboard:8080",
        timeout=5.0,
        retries=1,
        transport=transport,
    )

    response = await client.register(
        bootstrap_token="bt_valid_token_24h",
        agent_name="DevOps SRE Agent",
        version="0.1.0",
        capabilities=[{"name": "DockerTool", "category": "devops"}],
    )

    assert response.agent_id == "agent-uuid-12345"
    assert response.name == "DevOps SRE Agent"
    assert response.permanent_secret == "perm_secret_val_999"
    assert "Bearer bt_valid_token_24h" in captured_request["headers"]["authorization"]
    assert "/api/v1/agents/register" in captured_request["url"]


@pytest.mark.asyncio
async def test_dashboard_registration_fallback_on_404() -> None:
    """Valida que si /api/v1/agents/register devuelve 404, reintente con /api/agents/register."""
    urls_called: list[str] = []

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        urls_called.append(url)

        if "/api/v1/agents/register" in url:
            return httpx.Response(404, json={"error": "Not Found"})

        return httpx.Response(
            200,
            json={
                "message": "OK",
                "agent_id": "fallback-agent-id",
                "name": "Fallback Agent",
                "status": "ACTIVE",
                "permanent_secret": "fallback_secret",
            },
        )

    transport = httpx.MockTransport(mock_handler)
    client = DashboardRegistrationClient(
        dashboard_url="http://test-dashboard:8080",
        timeout=5.0,
        retries=1,
        transport=transport,
    )

    response = await client.register(bootstrap_token="bt_fallback")
    assert response.agent_id == "fallback-agent-id"
    assert len(urls_called) == 2
    assert "/api/v1/agents/register" in urls_called[0]
    assert "/api/agents/register" in urls_called[1]


@pytest.mark.asyncio
async def test_dashboard_registration_401_expired() -> None:
    """Valida que un token expirado o inválido lance RegistrationAuthError."""

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"error": "Unauthorized", "message": "Bootstrap token expirado o inválido"},
        )

    transport = httpx.MockTransport(mock_handler)
    client = DashboardRegistrationClient(
        dashboard_url="http://test-dashboard:8080", retries=1, transport=transport
    )

    with pytest.raises(RegistrationAuthError) as exc_info:
        await client.register(bootstrap_token="bt_expired_token")

    assert "HTTP 401" in str(exc_info.value)


@pytest.mark.asyncio
async def test_dashboard_registration_409_conflict() -> None:
    """Valida que un token ya consumido lance RegistrationConflictError."""

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            409,
            json={
                "error": "Conflict",
                "message": "Bootstrap token ya ha sido consumido previamente",
            },
        )

    transport = httpx.MockTransport(mock_handler)
    client = DashboardRegistrationClient(
        dashboard_url="http://test-dashboard:8080", retries=1, transport=transport
    )

    with pytest.raises(RegistrationConflictError) as exc_info:
        await client.register(bootstrap_token="bt_consumed_token")

    assert "HTTP 409" in str(exc_info.value)


@pytest.mark.asyncio
async def test_dashboard_registration_retry_success() -> None:
    """Valida que ante un fallo 503 inicial, el cliente reintente y tenga éxito."""
    attempts = 0

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, json={"error": "Service Unavailable"})
        return httpx.Response(
            200,
            json={
                "message": "Registrado tras reintento",
                "agent_id": "retry-agent-id",
                "name": "Retry Agent",
                "status": "ACTIVE",
                "permanent_secret": "retry_secret_123",
            },
        )

    transport = httpx.MockTransport(mock_handler)
    client = DashboardRegistrationClient(
        dashboard_url="http://test-dashboard:8080",
        timeout=5.0,
        retries=2,
        backoff_factor=0.01,
        transport=transport,
    )

    response = await client.register(bootstrap_token="bt_retry_test")
    assert response.agent_id == "retry-agent-id"
    assert attempts == 2


@pytest.mark.asyncio
async def test_dashboard_registration_connection_failure() -> None:
    """Valida que ante caídas consecutivas de red se lance DashboardConnectionError."""

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused by target machine")

    transport = httpx.MockTransport(mock_handler)
    client = DashboardRegistrationClient(
        dashboard_url="http://test-dashboard:8080",
        timeout=5.0,
        retries=2,
        backoff_factor=0.01,
        transport=transport,
    )

    with pytest.raises(DashboardConnectionError):
        await client.register(bootstrap_token="bt_network_fail")


# --- Tests para auto_register_agent ---


@pytest.mark.asyncio
async def test_auto_register_skips_if_persisted_credentials_exist(
    temp_credentials_file: Path, sample_credentials: AgentCredentials
) -> None:
    """Si el archivo de credenciales ya existe en disco, se omiten llamadas al Dashboard."""
    CredentialStore.save(sample_credentials, temp_credentials_file)

    test_settings = Settings(
        CREDENTIALS_FILE=str(temp_credentials_file),
        AGENT_BOOTSTRAP_TOKEN="unused_token_should_not_be_called",
        AGENT_ID="jg_agente_local",
    )

    creds = await auto_register_agent(settings=test_settings)
    assert creds is not None
    assert creds.agent_id == sample_credentials.agent_id
    assert creds.permanent_secret == sample_credentials.permanent_secret
    assert sample_credentials.agent_id == test_settings.AGENT_ID
    assert sample_credentials.permanent_secret == test_settings.PERMANENT_AGENT_SECRET


@pytest.mark.asyncio
async def test_auto_register_skips_if_env_secret_present(temp_credentials_file: Path) -> None:
    """Si PERMANENT_AGENT_SECRET ya viene configurado en variables de entorno, se omite el registro."""
    test_settings = Settings(
        CREDENTIALS_FILE=str(temp_credentials_file),
        AGENT_ID="custom-env-agent-id",
        PERMANENT_AGENT_SECRET="env_secret_val_123",
        AGENT_BOOTSTRAP_TOKEN="unused_token",
    )

    creds = await auto_register_agent(settings=test_settings)
    assert creds is not None
    assert creds.agent_id == "custom-env-agent-id"
    assert creds.permanent_secret == "env_secret_val_123"


@pytest.mark.asyncio
async def test_auto_register_consumes_bootstrap_token_and_saves(
    temp_credentials_file: Path,
) -> None:
    """Flujo completo de registro: consume bootstrap token y persiste en disco."""

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "message": "Registrado exitosamente",
                "agent_id": "new-boot-agent-id",
                "name": "Bootstrapped Agent",
                "status": "ACTIVE",
                "permanent_secret": "new_permanent_secret_456",
                "registered_at": "2026-09-05T20:20:00Z",
            },
        )

    transport = httpx.MockTransport(mock_handler)
    client = DashboardRegistrationClient(
        dashboard_url="http://test-dashboard:8080",
        timeout=5.0,
        retries=1,
        transport=transport,
    )

    test_settings = Settings(
        CREDENTIALS_FILE=str(temp_credentials_file),
        AGENT_BOOTSTRAP_TOKEN="valid_bootstrap_token_abc",
        AGENT_NAME="Bootstrapped Agent",
        AGENT_ID="jg_agente_local",
    )
    registry = CapabilityRegistry()

    creds = await auto_register_agent(settings=test_settings, registry=registry, client=client)
    assert creds is not None
    assert creds.agent_id == "new-boot-agent-id"
    assert creds.permanent_secret == "new_permanent_secret_456"

    # Verificar que se guardó en disco
    loaded_from_disk = CredentialStore.load(temp_credentials_file)
    assert loaded_from_disk is not None
    assert loaded_from_disk.agent_id == "new-boot-agent-id"
    assert loaded_from_disk.permanent_secret == "new_permanent_secret_456"

    # Verificar que settings se sincronizaron
    assert test_settings.AGENT_ID == "new-boot-agent-id"
    assert test_settings.PERMANENT_AGENT_SECRET == "new_permanent_secret_456"


@pytest.mark.asyncio
async def test_auto_register_standalone_when_no_token_and_not_required(
    temp_credentials_file: Path,
) -> None:
    """Si no hay token ni credenciales y no es requerido, arranca en modo local."""
    test_settings = Settings(
        CREDENTIALS_FILE=str(temp_credentials_file),
        AGENT_BOOTSTRAP_TOKEN=None,
        REQUIRE_DASHBOARD_REGISTRATION=False,
    )

    creds = await auto_register_agent(settings=test_settings)
    assert creds is None


@pytest.mark.asyncio
async def test_auto_register_raises_when_required_and_missing(
    temp_credentials_file: Path,
) -> None:
    """Si REQUIRE_DASHBOARD_REGISTRATION=True y no hay credenciales, lanza RegistrationError."""
    test_settings = Settings(
        CREDENTIALS_FILE=str(temp_credentials_file),
        AGENT_BOOTSTRAP_TOKEN=None,
        REQUIRE_DASHBOARD_REGISTRATION=True,
    )

    with pytest.raises(RegistrationError):
        await auto_register_agent(settings=test_settings)


# --- Tests para Verificación de Credenciales (ISSUE-F08-T02) ---


@pytest.mark.asyncio
async def test_verify_credentials_success() -> None:
    """Valida verificación exitosa de credencial permanente contra endpoint de heartbeat."""
    captured_request: dict[str, Any] = {}

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        captured_request["url"] = str(request.url)
        captured_request["headers"] = dict(request.headers)
        return httpx.Response(
            200,
            json={
                "status": "success",
                "message": "Heartbeat registrado exitosamente",
                "agent_id": "test-agent-123",
                "name": "Verified Agent",
                "agent_status": "ACTIVE",
            },
        )

    transport = httpx.MockTransport(mock_handler)
    client = DashboardRegistrationClient(
        dashboard_url="http://test-dashboard:8080",
        timeout=5.0,
        transport=transport,
    )

    result = await client.verify_credentials("test-agent-123", "secret-pass-456")
    assert result["agent_status"] == "ACTIVE"
    assert "/api/v1/agents/heartbeat" in captured_request["url"]
    assert "Bearer secret-pass-456" in captured_request["headers"]["authorization"]
    assert captured_request["headers"]["x-agent-id"] == "test-agent-123"


@pytest.mark.asyncio
async def test_verify_credentials_401_revoked() -> None:
    """Valida que credencial permanente rechazada por Dashboard lance RegistrationAuthError."""

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"error": "Unauthorized", "message": "Credencial permanente inválida o revocada"},
        )

    transport = httpx.MockTransport(mock_handler)
    client = DashboardRegistrationClient(
        dashboard_url="http://test-dashboard:8080",
        transport=transport,
    )

    with pytest.raises(RegistrationAuthError) as exc_info:
        await client.verify_credentials("revoked-agent-id", "invalid_secret")

    assert "HTTP 401" in str(exc_info.value)


@pytest.mark.asyncio
async def test_verify_credentials_connection_failure() -> None:
    """Valida que un fallo de red durante la verificación lance DashboardConnectionError."""

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")

    transport = httpx.MockTransport(mock_handler)
    client = DashboardRegistrationClient(
        dashboard_url="http://test-dashboard:8080",
        transport=transport,
    )

    with pytest.raises(DashboardConnectionError):
        await client.verify_credentials("agent-id-net", "secret-net")


@pytest.mark.asyncio
async def test_auto_register_reloads_persisted_and_verifies(
    temp_credentials_file: Path, sample_credentials: AgentCredentials
) -> None:
    """Valida que al arrancar con credenciales persistidas, verifique con Dashboard y marque verified=True."""
    CredentialStore.save(sample_credentials, temp_credentials_file)

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "success",
                "message": "Heartbeat registrado exitosamente",
                "agent_id": sample_credentials.agent_id,
                "agent_status": "ACTIVE",
            },
        )

    transport = httpx.MockTransport(mock_handler)
    client = DashboardRegistrationClient(
        dashboard_url="http://test-dashboard:8080",
        transport=transport,
    )

    test_settings = Settings(
        CREDENTIALS_FILE=str(temp_credentials_file),
        VERIFY_CREDENTIALS_ON_BOOT=True,
    )

    creds = await auto_register_agent(settings=test_settings, client=client)
    assert creds is not None
    assert creds.agent_id == sample_credentials.agent_id
    assert creds.verified is True


@pytest.mark.asyncio
async def test_auto_register_persisted_credentials_revoked_clears_disk(
    temp_credentials_file: Path, sample_credentials: AgentCredentials
) -> None:
    """Si las credenciales en disco fueron revocadas en el Dashboard, se limpian y se lanza RegistrationAuthError."""
    CredentialStore.save(sample_credentials, temp_credentials_file)
    assert CredentialStore.exists(temp_credentials_file)

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"error": "Unauthorized", "message": "Agente revocado"},
        )

    transport = httpx.MockTransport(mock_handler)
    client = DashboardRegistrationClient(
        dashboard_url="http://test-dashboard:8080",
        transport=transport,
    )

    test_settings = Settings(
        CREDENTIALS_FILE=str(temp_credentials_file),
        VERIFY_CREDENTIALS_ON_BOOT=True,
    )

    with pytest.raises(RegistrationAuthError):
        await auto_register_agent(settings=test_settings, client=client)

    # Debe haber eliminado el archivo inválido de disco
    assert not CredentialStore.exists(temp_credentials_file)


@pytest.mark.asyncio
async def test_auto_register_persisted_network_error_tolerates_and_proceeds(
    temp_credentials_file: Path, sample_credentials: AgentCredentials
) -> None:
    """Si el Dashboard no está disponible en boot, el agente arranca tolerante con verified=False."""
    CredentialStore.save(sample_credentials, temp_credentials_file)

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Dashboard is temporarily down")

    transport = httpx.MockTransport(mock_handler)
    client = DashboardRegistrationClient(
        dashboard_url="http://test-dashboard:8080",
        transport=transport,
    )

    test_settings = Settings(
        CREDENTIALS_FILE=str(temp_credentials_file),
        VERIFY_CREDENTIALS_ON_BOOT=True,
    )

    creds = await auto_register_agent(settings=test_settings, client=client)
    assert creds is not None
    assert creds.agent_id == sample_credentials.agent_id
    assert creds.verified is False


def test_reload_credentials_in_memory(
    temp_credentials_file: Path, sample_credentials: AgentCredentials
) -> None:
    """Valida la recarga explícita de credenciales modificadas en almacenamiento local."""
    test_settings = Settings(
        CREDENTIALS_FILE=str(temp_credentials_file),
        AGENT_ID="old-agent-id",
        PERMANENT_AGENT_SECRET=None,
    )

    # Antes de guardar
    assert reload_credentials(test_settings) is None

    # Guardar credenciales en disco
    CredentialStore.save(sample_credentials, temp_credentials_file)

    # Recargar
    reloaded = reload_credentials(test_settings)
    assert reloaded is not None
    assert reloaded.agent_id == sample_credentials.agent_id
    assert sample_credentials.agent_id == test_settings.AGENT_ID
    assert sample_credentials.permanent_secret == test_settings.PERMANENT_AGENT_SECRET
