# Contexto de Proyecto: jg_agente

> **Fecha de Actualización:** 4 de septiembre de 2026  
> **Estado Global del Proyecto:** Fase 01 en progreso (`ISSUE-F01-T01` e `ISSUE-F01-T02` completados)  
> **Próxima Tarea Inmediata:** `ISSUE-F01-T03` (Setup de CI/CD básico: Linting, Typechecking, Test Suite)  

---

## 1. Visión y Propósito

`jg_agente` es el **Execution Plane** del ecosistema jG: un motor autónomo de ejecución desacoplado de protocolos de transporte y construido sobre LangGraph. Su propósito es ejecutar ciclos cognitivos de razonamiento, planificación, invocación segura de herramientas y verificación.

---

## 2. Estado Actual del Repositorio

### 2.1 Tooling y Contenedores
- **Empaquetado Python:** `pyproject.toml` con estándares PEP 621 (`fastapi`, `langgraph`, `pydantic`, `sqlalchemy[asyncio]`, `asyncpg`, `httpx`).
- **Contenedores:**
  - `Dockerfile`: Construcción multi-stage (builder/runner) con usuario no-root `10001:10001`.
  - `docker-compose.yml`: Orquestación de `jg_agente` y `jg_agente_postgres` (`postgres:16-alpine`) en red bridge privada.
- **Herramientas de Calidad de Código:**
  - Ruff, MyPy (`strict`), Pytest integrados en `scripts/check.sh`.

### 2.2 Estructura de Paquetes y Archivos
```text
jg_agente/
├── Dockerfile                # Multi-stage build (builder / runner no-root)
├── docker-compose.yml        # Orquestación con PostgreSQL (red jg_agente_net)
├── .env.example              # Plantilla de variables de entorno
├── pyproject.toml            # Dependencias y configuración de herramientas
├── .gitignore                # Exclusiones de control de versiones
├── app/
│   ├── __init__.py           # Versión 0.1.0
│   ├── main.py               # Servidor FastAPI con /health y ping a PostgreSQL
│   └── core/
│       ├── __init__.py       # Namespace Core
│       └── config.py         # Settings centralizados con Pydantic
├── tests/
│   ├── __init__.py
│   ├── test_bootstrap.py     # Smoke tests de dependencias
│   └── test_health_endpoint.py # Pruebas funcionales de endpoints FastAPI
├── scripts/
│   └── check.sh              # Script unificado de validación (Ruff + MyPy + Pytest)
└── docs/
    └── issues/
        ├── ISSUE-F01-T01-analysis.md
        ├── ISSUE-F01-T01-walkthrough.md
        ├── ISSUE-F01-T01-PROJECT_CONTEXT.md
        ├── ISSUE-F01-T02-analysis.md
        ├── ISSUE-F01-T02-walkthrough.md
        └── ISSUE-F01-T02-PROJECT_CONTEXT.md
```

---

## 3. Estado de la Fase Actual (Fase 01)

| Issue ID | Título | Estado |
| :--- | :--- | :--- |
| `ISSUE-F01-T01` | Estructura base del repositorio, configuración pyproject.toml y dependencias | **COMPLETADO** |
| `ISSUE-F01-T02` | Configuración de Dockerfile y Docker Compose para desarrollo local | **COMPLETADO** |
| `ISSUE-F01-T03` | Setup de CI/CD básico (Linting, Typechecking, Test Suite) | **PENDIENTE** |
