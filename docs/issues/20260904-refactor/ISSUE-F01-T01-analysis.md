# Análisis Técnico: ISSUE-F01-T01 — Estructura base del repositorio, configuración pyproject.toml y dependencias

> **Estado del Documento:** FINALIZADO  
> **Issue ID:** `ISSUE-F01-T01`  
> **Fase:** FASE 01 — Bootstrap, Documentación y Tooling  
> **Prioridad:** High  
> **Complejidad Estimada:** S  
> **Dependencias:** Ninguna  

---

## 1. Objetivo del Issue

Establecer los cimientos del entorno de desarrollo para el proyecto `jg_agente` (Execution Plane). Configurar la estructura de empaquetado de Python moderna mediante `pyproject.toml`, definir las dependencias troncales del motor (FastAPI, LangGraph, Pydantic V2, SQLAlchemy, asyncpg, httpx) y habilitar herramientas de análisis estático estricto (Ruff, MyPy) y testing automatizado (Pytest) ejecutables mediante un comando unificado.

---

## 2. Requerimientos y Criterios de Aceptación

1. **Gestión de Dependencias y Proyecto:**
   - Archivo `pyproject.toml` configurado conforme al estándar PEP 621 (`[project]`), declarando dependencias de producción y dependencias de desarrollo (`[project.optional-dependencies]`).
   - Soporte para Python >= 3.11.
2. **Herramientas de Calidad de Código:**
   - **Ruff:** Configurado para linter (`select = ["E", "F", "I", "N", "UP", "B", "C4", "SIM"]`) y formateador de código.
   - **MyPy:** Configurado en modo estricto (`strict = true`, `disallow_untyped_defs = true`, `disallow_incomplete_defs = true`).
   - **Pytest:** Configurado con soporte asíncrono (`asyncio_mode = "auto"`) y descubrimiento de tests en `tests/`.
3. **Comando Único de Validación:**
   - Script ejecutable `scripts/check.sh` que ejecute secuencialmente Ruff, MyPy y Pytest, retornando código de salida 0 únicamente si todas las verificaciones pasan.
4. **Smoke Test Inicial:**
   - Test de verificación que valide metadatos del paquete, compatibilidad de versión de Python y correcta importación de todas las librerías base.

---

## 3. Decisiones Técnicas y Diseño

- **Gestor de entorno:** Entorno virtual aislado en `.venv/` con `pip` actualizado.
- **Inclusión de dependencias core:**
  - `fastapi` y `uvicorn`: Para el servidor de API interna del agente.
  - `langgraph` y `langchain-core`: Para el motor de orquestación cognitiva por grafos de estado.
  - `pydantic` (v2) y `pydantic-settings`: Para contratos y validación de tipos inmutables.
  - `sqlalchemy` (v2 async) y `asyncpg`: Para la persistencia de checkpoints y auditoría en PostgreSQL.
  - `httpx`: Para el cliente HTTP asíncrono hacia `jg_dashboard`.
- **Estructura del Repositorio:**
  ```text
  jg_agente/
  ├── pyproject.toml
  ├── .gitignore
  ├── app/
  │   ├── __init__.py
  │   └── core/
  │       └── __init__.py
  ├── tests/
  │   ├── __init__.py
  │   └── test_bootstrap.py
  ├── scripts/
  │   └── check.sh
  └── docs/
      └── issues/
          ├── ISSUE-F01-T01-analysis.md
          ├── ISSUE-F01-T01-walkthrough.md
          └── ISSUE-F01-T01-PROJECT_CONTEXT.md
  ```

---

## 4. Plan de Verificación

- Ejecución de `scripts/check.sh`:
  - `ruff check app tests`
  - `ruff format --check app tests`
  - `mypy app tests`
  - `pytest tests`
