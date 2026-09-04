# Contexto de Proyecto: jg_agente

> **Fecha de Actualización:** 4 de septiembre de 2026  
> **Estado Global del Proyecto:** Fase 01 COMPLETADA AL 100% (`ISSUE-F01-T01`, `ISSUE-F01-T02` e `ISSUE-F01-T03` finalizados)  
> **Próxima Tarea Inmediata:** `ISSUE-F02-T01` (Implementación de contratos AgentInput y AgentOutput en Fase 02: Contratos y Modelos Core)  

---

## 1. Visión y Propósito

`jg_agente` es el **Execution Plane** del ecosistema jG: un motor autónomo de ejecución desacoplado de protocolos de transporte y construido sobre LangGraph. Su propósito es ejecutar ciclos cognitivos de razonamiento, planificación, invocación segura de herramientas y verificación.

---

## 2. Estado Actual del Repositorio

### 2.1 Tooling, Contenedores y CI/CD
- **Empaquetado Python:** `pyproject.toml` bajo estándar PEP 621 con dependencias troncales instaladas y probadas.
- **Contenedores:**
  - `Dockerfile`: Construcción multi-stage (builder/runner) con usuario no-root `10001:10001` y healthcheck activo.
  - `docker-compose.yml`: Orquestación funcional de `jg_agente` y `jg_agente_postgres` en red bridge privada `jg_agente_net`.
- **Pipeline CI/CD:**
  - `.gitlab-ci.yml`: Pipeline con etapas `lint` (`lint:ruff`) y `test` (`typecheck:mypy`, `test:pytest`).
- **Verificación Local:**
  - `scripts/check.sh`: Comando único de verificación local passing al 100% sin advertencias.

### 2.2 Estructura del Repositorio
```text
jg_agente/
├── .gitlab-ci.yml            # Pipeline de integración continua GitLab CI
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
        ├── ISSUE-F01-T02-PROJECT_CONTEXT.md
        ├── ISSUE-F01-T03-analysis.md
        ├── ISSUE-F01-T03-walkthrough.md
        └── ISSUE-F01-T03-PROJECT_CONTEXT.md
```

---

## 3. Resumen de Fases y Próximos Pasos

### Fase 01: Bootstrap, Documentación y Tooling (100% COMPLETADA)
- [x] `ISSUE-F01-T01`: Estructura base del repositorio, configuración pyproject.toml y dependencias.
- [x] `ISSUE-F01-T02`: Configuración de Dockerfile y Docker Compose para desarrollo local.
- [x] `ISSUE-F01-T03`: Setup de CI/CD básico (Linting, Typechecking, Test Suite).

### Fase 02: Contratos y Modelos Core (SIGUIENTE FASE)
- [ ] `ISSUE-F02-T01`: Implementación de contratos AgentInput y AgentOutput.
- [ ] `ISSUE-F02-T02`: Contrato definitivo de AgentTool y ToolResult.
- [ ] `ISSUE-F02-T03`: Contrato de compensación y Rollback en AgentTool.
- [ ] `ISSUE-F02-T04`: Definición del estado global del agente (AgentState).
