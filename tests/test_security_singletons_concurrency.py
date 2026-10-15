# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez <contacto@javiergalvez.com>
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Pruebas de concurrencia y seguridad multihilo para singletons de seguridad (AGENTE-CONC-01).

Valida que:
1. `get_security_guard()` es thread-safe y garantiza una única instancia bajo contención masiva.
2. `get_ssrf_validator()` es thread-safe y garantiza una única instancia bajo contención masiva.
3. `get_security_audit_logger()` y `get_audit_logger()` son equivalentes y thread-safe.
4. El ciclo de vida (`lifespan`) pre-inicializa de forma determinista todos los singletons de seguridad.
"""

import asyncio
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock, patch

import pytest

import app.security.audit as audit_module
import app.security.guard as guard_module
import app.security.ssrf as ssrf_module
from app.main import app, lifespan
from app.security import (
    SecurityAuditLogger,
    SecurityGuard,
    SSRFValidator,
    get_audit_logger,
    get_security_audit_logger,
    get_security_guard,
    get_ssrf_validator,
)


@pytest.fixture(autouse=True)
def clean_security_singletons() -> Generator[None, None, None]:
    """Restaura los singletons antes y después de cada test para aislar el estado."""
    orig_guard = guard_module._default_security_guard
    orig_ssrf = ssrf_module._default_ssrf_validator
    orig_audit = audit_module._default_audit_logger

    guard_module._default_security_guard = None
    ssrf_module._default_ssrf_validator = None
    audit_module._default_audit_logger = None

    yield

    guard_module._default_security_guard = orig_guard
    ssrf_module._default_ssrf_validator = orig_ssrf
    audit_module._default_audit_logger = orig_audit


def test_security_guard_concurrent_initialization_threads() -> None:
    """Verifica que múltiples hilos concurrentes inicialicen exactamente la misma instancia de SecurityGuard."""
    num_workers = 50

    def worker() -> SecurityGuard:
        return get_security_guard()

    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = [executor.submit(worker) for _ in range(num_workers)]
        results = [f.result() for f in futures]

    assert len(results) == num_workers
    first_instance = results[0]
    assert isinstance(first_instance, SecurityGuard)
    for instance in results[1:]:
        assert instance is first_instance
        assert id(instance) == id(first_instance)


@pytest.mark.asyncio
async def test_security_guard_concurrent_initialization_coroutines() -> None:
    """Verifica que múltiples corrutinas concurrentes obtengan exactamente la misma instancia."""
    num_coros = 50

    async def coro_worker() -> SecurityGuard:
        # Forzar un context switch previo para maximizar contención en loop
        await asyncio.sleep(0.001)
        return get_security_guard()

    tasks = [asyncio.create_task(coro_worker()) for _ in range(num_coros)]
    results = await asyncio.gather(*tasks)

    assert len(results) == num_coros
    first_instance = results[0]
    for instance in results[1:]:
        assert instance is first_instance


def test_ssrf_validator_concurrent_initialization_threads() -> None:
    """Verifica que múltiples hilos concurrentes inicialicen exactamente la misma instancia de SSRFValidator."""
    num_workers = 50

    def worker() -> SSRFValidator:
        return get_ssrf_validator()

    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = [executor.submit(worker) for _ in range(num_workers)]
        results = [f.result() for f in futures]

    assert len(results) == num_workers
    first_instance = results[0]
    assert isinstance(first_instance, SSRFValidator)
    for instance in results[1:]:
        assert instance is first_instance
        assert id(instance) == id(first_instance)


@pytest.mark.asyncio
async def test_ssrf_validator_concurrent_initialization_coroutines() -> None:
    """Verifica que múltiples corrutinas concurrentes obtengan exactamente la misma instancia de SSRFValidator."""
    num_coros = 50

    async def coro_worker() -> SSRFValidator:
        await asyncio.sleep(0.001)
        return get_ssrf_validator()

    tasks = [asyncio.create_task(coro_worker()) for _ in range(num_coros)]
    results = await asyncio.gather(*tasks)

    assert len(results) == num_coros
    first_instance = results[0]
    for instance in results[1:]:
        assert instance is first_instance


def test_audit_logger_concurrent_initialization_threads() -> None:
    """Verifica concurrencia multihilo y equivalencia entre get_security_audit_logger y get_audit_logger."""
    num_workers = 50

    def worker(idx: int) -> SecurityAuditLogger:
        # Alternar entre la función formal y el alias canónico
        if idx % 2 == 0:
            return get_security_audit_logger()
        return get_audit_logger()

    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = [executor.submit(worker, i) for i in range(num_workers)]
        results = [f.result() for f in futures]

    assert len(results) == num_workers
    first_instance = results[0]
    assert isinstance(first_instance, SecurityAuditLogger)
    for instance in results[1:]:
        assert instance is first_instance
        assert id(instance) == id(first_instance)


@pytest.mark.asyncio
async def test_audit_logger_concurrent_initialization_coroutines() -> None:
    """Verifica contención asíncrona y unicidad para SecurityAuditLogger."""
    num_coros = 50

    async def coro_worker(idx: int) -> SecurityAuditLogger:
        await asyncio.sleep(0.001)
        if idx % 2 == 0:
            return get_security_audit_logger()
        return get_audit_logger()

    tasks = [asyncio.create_task(coro_worker(i)) for i in range(num_coros)]
    results = await asyncio.gather(*tasks)

    assert len(results) == num_coros
    first_instance = results[0]
    for instance in results[1:]:
        assert instance is first_instance


@pytest.mark.asyncio
async def test_lifespan_preinitializes_security_singletons() -> None:
    """Verifica que el lifespan de FastAPI pre-inicializa todos los singletons de seguridad."""
    assert guard_module._default_security_guard is None
    assert ssrf_module._default_ssrf_validator is None
    assert audit_module._default_audit_logger is None

    mock_checkpointer = AsyncMock()
    mock_plugin_manager = AsyncMock()
    mock_plugin_manager.startup = AsyncMock()
    mock_plugin_manager.shutdown = AsyncMock()

    with (
        patch("app.main.init_agent_capabilities", return_value=({}, mock_plugin_manager)),
        patch("app.main.get_checkpointer", return_value=mock_checkpointer),
        patch("app.main.auto_register_agent", new_callable=AsyncMock, return_value=None),
        patch("app.main.close_checkpointer") as mock_close_checkpointer,
    ):
        async with lifespan(app):
            # En el bloque activo de lifespan, todos los singletons deben estar pre-inicializados
            assert guard_module._default_security_guard is not None
            assert ssrf_module._default_ssrf_validator is not None
            assert audit_module._default_audit_logger is not None
            assert isinstance(guard_module._default_security_guard, SecurityGuard)
            assert isinstance(ssrf_module._default_ssrf_validator, SSRFValidator)
            assert isinstance(audit_module._default_audit_logger, SecurityAuditLogger)

        # En shutdown, close_checkpointer es invocado
        mock_close_checkpointer.assert_called_once()
