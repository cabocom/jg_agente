# Contexto de Proyecto: jg_agente

> **Fecha de Actualización:** 4 de septiembre de 2026  
> **Estado Global del Proyecto:** Fase 01 en progreso (`ISSUE-F01-T01` completado)  
> **Próxima Tarea Inmediata:** `ISSUE-F01-T02` (Configuración de Dockerfile y Docker Compose para desarrollo local)  

---

## 1. Visión y Propósito

`jg_agente` es el **Execution Plane** del ecosistema jG: un motor autónomo de ejecución desacoplado de protocolos de transporte y construido sobre LangGraph. Su propósito es ejecutar ciclos cognitivos de razonamiento, planificación, invocación segura de herramientas y verificación.

### Principios Troncales:
- **Agnosticismo Radical:** Cero lógica condicional por tipo de agente (`if devops:`, `if conversational:`).
- **Sin Interfaces Externas:** No maneja protocolos externos (Asterisk, Telegram, Webhooks). Consume `AgentInput` y genera `AgentOutput`.
- **Inversión de Control:** Los plugins aportan herramientas (`AgentTool`) y engines; el Core orquesta.
- **Seguridad Sandbox:** Invocación de herramientas protegida por `SecurityGuard` (SSRF, RiskLevel, HITL).
- **Persistencia Aislada:** Base de datos PostgreSQL propia para el agente con prefijo `core_*`.

---

## 2. Estado Actual del Repositorio

### 2.1 Tooling y Calidad de Código
- `pyproject.toml` configurado con dependencias troncales: `fastapi`, `langgraph`, `pydantic`, `sqlalchemy[asyncio]`, `asyncpg`, `httpx`, `uvicorn`.
- Herramientas de calidad activas:
  - **Ruff:** Linter y formateador estricto.
  - **MyPy:** Verificación estática con `strict = true`.
  - **Pytest:** Suite asíncrona de pruebas.
- Script unificado de validación: `./scripts/check.sh`.

### 2.2 Estructura de Paquetes
```text
jg_agente/
├── pyproject.toml
├── .gitignore
├── app/
│   ├── __init__.py           # Versión 0.1.0
│   └── core/
│       └── __init__.py       # Namespace del Core
├── tests/
│   ├── __init__.py
│   └── test_bootstrap.py     # Smoke tests de dependencias y Python
├── scripts/
│   └── check.sh              # Script de validación integral (Ruff + MyPy + Pytest)
└── docs/
    └── issues/
        ├── ISSUE-F01-T01-analysis.md
        ├── ISSUE-F01-T01-walkthrough.md
        └── ISSUE-F01-T01-PROJECT_CONTEXT.md
```

---

## 3. Estado de la Fase Actual (Fase 01)

| Issue ID | Título | Estado |
| :--- | :--- | :--- |
| `ISSUE-F01-T01` | Estructura base del repositorio, configuración pyproject.toml y dependencias | **COMPLETADO** |
| `ISSUE-F01-T02` | Configuración de Dockerfile y Docker Compose para desarrollo local | Pendiente |
| `ISSUE-F01-T03` | Setup de CI/CD básico (Linting, Typechecking, Test Suite) | Pendiente |
