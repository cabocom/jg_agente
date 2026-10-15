# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez <contacto@javiergalvez.com>
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Pruebas unitarias de verificación estática de Dockerfile y configuración de workers (AGENTE-INFRA-01).

Valida que:
1. La imagen base esté fijada a python:3.12.6-slim en las etapas builder y runner.
2. La variable UVICORN_WORKERS esté declarada en la directiva ENV.
3. El comando CMD parametrice --workers con exec y valor por defecto.
4. Settings en app.core.config exponga UVICORN_WORKERS con valor por defecto >= 1.
"""

from pathlib import Path

from app.core.config import Settings, settings


def test_dockerfile_pinned_python_version() -> None:
    """Verifica que Dockerfile fije la versión de Python a 3.12.6-slim en ambas etapas."""
    dockerfile_path = Path(__file__).resolve().parent.parent / "Dockerfile"
    assert dockerfile_path.exists(), f"No se encontró Dockerfile en {dockerfile_path}"

    content = dockerfile_path.read_text(encoding="utf-8")
    lines = [line.strip() for line in content.splitlines()]

    # Etapa builder
    builder_lines = [line for line in lines if line.startswith("FROM") and "builder" in line]
    assert len(builder_lines) == 1, "Debe existir una única directiva FROM builder"
    assert "python:3.12.6-slim" in builder_lines[0], (
        f"La etapa builder debe usar python:3.12.6-slim. Encontrado: {builder_lines[0]}"
    )

    # Etapa runner
    runner_lines = [line for line in lines if line.startswith("FROM") and "runner" in line]
    assert len(runner_lines) == 1, "Debe existir una única directiva FROM runner"
    assert "python:3.12.6-slim" in runner_lines[0], (
        f"La etapa runner debe usar python:3.12.6-slim. Encontrado: {runner_lines[0]}"
    )


def test_dockerfile_uvicorn_workers_configuration() -> None:
    """Verifica que Dockerfile defina UVICORN_WORKERS y parametrice CMD con exec uvicorn."""
    dockerfile_path = Path(__file__).resolve().parent.parent / "Dockerfile"
    content = dockerfile_path.read_text(encoding="utf-8")

    assert "UVICORN_WORKERS=2" in content or "UVICORN_WORKERS" in content, (
        "Dockerfile debe definir la variable de entorno UVICORN_WORKERS en ENV"
    )

    # Verificar CMD con exec y --workers
    cmd_lines = [line.strip() for line in content.splitlines() if line.strip().startswith("CMD [")]
    assert len(cmd_lines) == 1, "Debe existir una única directiva CMD final"
    cmd_line = cmd_lines[0]
    assert "exec uvicorn" in cmd_line, (
        "CMD debe invocar 'exec uvicorn' para preservar señales POSIX"
    )
    assert "--workers" in cmd_line, "CMD debe incluir el flag --workers"
    assert "UVICORN_WORKERS" in cmd_line, "CMD debe referenciar la variable UVICORN_WORKERS"


def test_settings_uvicorn_workers() -> None:
    """Verifica que Settings exponga UVICORN_WORKERS y valide límites."""
    assert hasattr(settings, "UVICORN_WORKERS")
    assert settings.UVICORN_WORKERS >= 1

    custom_settings = Settings(UVICORN_WORKERS=4)
    assert custom_settings.UVICORN_WORKERS == 4
