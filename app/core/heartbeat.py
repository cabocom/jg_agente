"""Servicio en segundo plano para el envío periódico de heartbeats hacia jg_dashboard."""

import asyncio
import contextlib
import json
import logging
import os
import resource
import sys
import time
from datetime import UTC, datetime
from typing import Any, cast

import httpx

from app import __version__
from app.core.config import Settings
from app.core.registry import CapabilityRegistry
from app.security.auth import compute_canonical_string, compute_hmac_signature

logger = logging.getLogger("jg_agente.heartbeat")


def collect_system_metrics(
    start_time: float,
    registry: CapabilityRegistry | None = None,
) -> dict[str, Any]:
    """Recopila telemetría y métricas de salud del sistema, proceso y capacidades activas."""
    # Uso de memoria portable entre plataformas
    # En Linux, ru_maxrss se reporta en kilobytes; en macOS (Darwin), en bytes.
    ru_resource = resource.getrusage(resource.RUSAGE_SELF)
    if sys.platform == "darwin":
        memory_mb = round(ru_resource.ru_maxrss / (1024 * 1024), 2)
    else:
        memory_mb = round(ru_resource.ru_maxrss / 1024, 2)

    uptime_sec = round(time.time() - start_time, 2)
    cpu_time = ru_resource.ru_utime + ru_resource.ru_stime
    cpu_count = os.cpu_count() or 1
    cpu_percent = min(round((cpu_time / max(uptime_sec, 1.0)) * 100 / cpu_count, 1), 100.0)

    return {
        "version": __version__,
        "uptime_seconds": uptime_sec,
        "memory_mb": memory_mb,
        "cpu_percent": cpu_percent,
        "tools_count": len(registry.list_tools()) if registry is not None else 0,
        "plugins_count": len(registry.list_plugins()) if registry is not None else 0,
        "engines_count": len(registry.list_engines()) if registry is not None else 0,
        "api_url": os.getenv("AGENT_API_URL")
        or f"http://{os.getenv('AGENT_ID', 'jg_agente')}:8000",
        "timestamp": datetime.now(UTC).isoformat(),
        "platform": sys.platform,
    }


class HeartbeatService:
    """Gestiona el ciclo de vida del bucle en segundo plano de latidos (heartbeats) hacia el Dashboard."""

    def __init__(
        self,
        settings: Settings,
        registry: CapabilityRegistry | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.registry = registry
        self.transport = transport
        self._running: bool = False
        self._task: asyncio.Task[None] | None = None
        self._start_time: float = time.time()
        self.last_successful_heartbeat: str | None = None
        self.last_error: str | None = None
        self.heartbeat_count: int = 0
        self.failed_count: int = 0

    @property
    def is_running(self) -> bool:
        """Indica si la tarea en segundo plano está activa."""
        return self._running and self._task is not None and not self._task.done()

    async def send_heartbeat(
        self,
        agent_id: str,
        permanent_secret: str,
        status: str = "ACTIVE",
    ) -> dict[str, Any] | None:
        """Emite una petición individual de heartbeat hacia el Dashboard."""
        metrics = collect_system_metrics(self._start_time, self.registry)

        payload = {
            "agent_id": agent_id,
            "status": status,
            "metrics": metrics,
        }

        timestamp = int(time.time())
        raw_body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        canonical_v1 = compute_canonical_string(
            "POST", "/api/v1/agents/heartbeat", timestamp, raw_body
        )
        sig_v1 = compute_hmac_signature(permanent_secret, canonical_v1)

        headers = {
            "X-Agent-ID": agent_id,
            "X-Timestamp": str(timestamp),
            "X-Signature": sig_v1,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": f"jg_agente/{__version__}",
        }

        endpoint_v1 = f"{self.settings.DASHBOARD_URL.rstrip('/')}/api/v1/agents/heartbeat"
        endpoint_fallback = f"{self.settings.DASHBOARD_URL.rstrip('/')}/api/agents/heartbeat"

        try:
            async with httpx.AsyncClient(
                timeout=self.settings.HEARTBEAT_TIMEOUT_SECONDS, transport=self.transport
            ) as client:
                response = await client.post(endpoint_v1, content=raw_body, headers=headers)
                if response.status_code == 404:
                    canonical_fallback = compute_canonical_string(
                        "POST", "/api/agents/heartbeat", timestamp, raw_body
                    )
                    headers_fallback = dict(headers)
                    headers_fallback["X-Signature"] = compute_hmac_signature(
                        permanent_secret, canonical_fallback
                    )
                    response = await client.post(
                        endpoint_fallback, content=raw_body, headers=headers_fallback
                    )

                if response.status_code == 200:
                    self.last_successful_heartbeat = datetime.now(UTC).isoformat()
                    self.last_error = None
                    self.heartbeat_count += 1
                    logger.debug(
                        "Heartbeat emitido exitosamente hacia Dashboard (Agent ID: %s, latido #%d).",
                        agent_id,
                        self.heartbeat_count,
                    )
                    return cast(dict[str, Any], response.json())

                if response.status_code in (401, 403):
                    msg = (
                        f"Credencial permanente rechazada por el Dashboard en heartbeat "
                        f"(HTTP {response.status_code}): {response.text}"
                    )
                    logger.critical(msg)
                    self.last_error = msg
                    self.failed_count += 1
                    return None

                msg = (
                    f"Dashboard devolvió código no exitoso en heartbeat "
                    f"(HTTP {response.status_code}): {response.text}"
                )
                logger.warning(msg)
                self.last_error = msg
                self.failed_count += 1
                return None

        except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as e:
            msg = f"Dashboard no disponible temporalmente en heartbeat ({self.settings.DASHBOARD_URL}): {e}"
            logger.warning(msg)
            self.last_error = msg
            self.failed_count += 1
            return None
        except Exception as e:
            msg = f"Error inesperado al emitir heartbeat: {e}"
            logger.warning(msg)
            self.last_error = msg
            self.failed_count += 1
            return None

    async def run_loop(self) -> None:
        """Bucle recurrente que emite latidos periódicos a intervalos configurados."""
        interval = self.settings.HEARTBEAT_INTERVAL_SECONDS
        agent_id = self.settings.AGENT_ID
        secret = self.settings.PERMANENT_AGENT_SECRET

        if not secret or not agent_id or agent_id == "jg_agente_local":
            logger.warning(
                "Bucle de heartbeat no iniciado: agente sin credenciales permanentes configuradas."
            )
            self._running = False
            return

        logger.info(
            "Iniciando bucle de heartbeat hacia %s cada %d segundos (Agent ID: %s)...",
            self.settings.DASHBOARD_URL,
            interval,
            agent_id,
        )

        while self._running:
            # Releer valores dinámicos por si rotaron en memoria
            current_id = self.settings.AGENT_ID
            current_secret = self.settings.PERMANENT_AGENT_SECRET

            if current_secret and current_id and current_id != "jg_agente_local":
                await self.send_heartbeat(
                    agent_id=current_id,
                    permanent_secret=current_secret,
                )

            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break

        logger.info("Bucle de heartbeat finalizado.")

    def start(self) -> asyncio.Task[None] | None:
        """Inicia el bucle asíncrono en segundo plano si hay credenciales permanentes."""
        if self._running or (self._task is not None and not self._task.done()):
            return self._task

        secret = self.settings.PERMANENT_AGENT_SECRET
        if not secret:
            logger.info("HeartbeatService no iniciado: sin PERMANENT_AGENT_SECRET disponible.")
            return None

        self._running = True
        self._task = asyncio.create_task(self.run_loop(), name="heartbeat_service_loop")
        return self._task

    async def stop(self) -> None:
        """Detiene de forma limpia y ordenada el bucle en segundo plano."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
            logger.info("HeartbeatService detenido correctamente.")
