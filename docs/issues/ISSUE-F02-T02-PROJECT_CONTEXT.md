# Contexto de Proyecto: jg_agente

> **Fecha de Actualización:** 4 de septiembre de 2026  
> **Estado Global del Proyecto:** Fase 01 completada (100%), Fase 02 con `ISSUE-F02-T01` e `ISSUE-F02-T02` completados.  
> **Próxima Tarea Inmediata:** `ISSUE-F02-T03` (Contrato de compensación y Rollback en AgentTool).  

---

## 1. Resumen Ejecutivo de la Tarea Completada

Se ha implementado el archivo `app/models/tools.py`, conteniendo los contratos troncales `AgentTool`, `ToolResult`, `RiskLevel` y `ToolType`.

Con esta incorporación, `jg_agente` cuenta con la infraestructura canónica para que los plugins declaren capacidades de negocio con información rica de seguridad (permisos, riesgo, SSRF), esquemas de validación de argumentos para function calling con LLMs, y metadatos para compensación/rollback.

---

## 2. Estado Actual del Repositorio

```text
jg_agente/
├── .gitlab-ci.yml            # Pipeline CI/CD (lint, test, build a registry.cabocom.net con tag de rama)
├── Dockerfile                # Multi-stage build (builder / runner no-root)
├── docker-compose.yml        # Orquestación con PostgreSQL (red jg_agente_net)
├── .env.example              # Plantilla de variables de entorno
├── pyproject.toml            # Dependencias y configuración de herramientas
├── .gitignore                # Exclusiones de control de versiones
├── app/
│   ├── __init__.py           # Versión 0.1.0
│   ├── main.py               # Servidor FastAPI con /health y ping a PostgreSQL
│   ├── core/
│   │   ├── __init__.py
│   │   └── config.py         # Settings centralizados con Pydantic
│   └── models/
│       ├── __init__.py       # Exportación de contratos públicos
│       ├── io.py             # AgentInput, AgentOutput, UserContext, ExecutionStatus
│       └── tools.py          # AgentTool, ToolResult, RiskLevel, ToolType
├── tests/
│   ├── __init__.py
│   ├── test_bootstrap.py     # Smoke tests de dependencias
│   ├── test_health_endpoint.py # Pruebas funcionales de endpoints FastAPI
│   ├── test_io_models.py     # Pruebas unitarias de contratos AgentInput y AgentOutput
│   └── test_tool_models.py   # Pruebas unitarias de contratos AgentTool y ToolResult
├── scripts/
│   └── check.sh              # Script unificado de validación (Ruff + MyPy + Pytest)
└── docs/
    └── issues/
        ├── ISSUE-F01-T01-*.md
        ├── ISSUE-F01-T02-*.md
        ├── ISSUE-F01-T03-*.md
        ├── ISSUE-F02-T01-*.md
        ├── ISSUE-F02-T02-analysis.md
        ├── ISSUE-F02-T02-walkthrough.md
        └── ISSUE-F02-T02-PROJECT_CONTEXT.md
```

---

## 3. Estado de la Fase 02: Contratos y Modelos Core

- [x] **`ISSUE-F02-T01`**: Implementación de contratos AgentInput y AgentOutput.
- [x] **`ISSUE-F02-T02`**: Contrato definitivo de AgentTool y ToolResult.
- [ ] **`ISSUE-F02-T03`**: Contrato de compensación y Rollback en AgentTool.
- [ ] **`ISSUE-F02-T04`**: Definición del estado global del agente (AgentState).
