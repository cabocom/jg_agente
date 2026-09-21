# Análisis Técnico: ISSUE-F01-T03 — Setup de CI/CD básico (Linting, Typechecking, Test Suite)

> **Estado del Documento:** FINALIZADO  
> **Issue ID:** `ISSUE-F01-T03`  
> **Fase:** FASE 01 — Bootstrap, Documentación y Tooling  
> **Prioridad:** Medium  
> **Complejidad Estimada:** S  
> **Dependencias:** `ISSUE-F01-T01`  

---

## 1. Objetivo del Issue

Configurar el pipeline de Integración Continua (GitLab CI/CD) para el repositorio `jg_agente` mediante el archivo `.gitlab-ci.yml`. El pipeline debe asegurar que cada Merge Request o commit en ramas protegidas valide automáticamente el cumplimiento de las directrices de formato (Ruff), análisis estático de tipos en modo estricto (MyPy) y ejecución de la suite de pruebas automatizadas (Pytest).

---

## 2. Requerimientos y Criterios de Aceptación

1. **Configuración de Pipeline ([.gitlab-ci.yml](../../../.gitlab-ci.yml)):**
   - Etapas (`stages`): `lint`, `test` y `build`.
   - Imagen base estándar: `python:3.12-slim` para lint/test y `docker:24.0.7` con dind para build.
   - Estrategia de caché para dependencias pip (`PIP_CACHE_DIR: "$CI_PROJECT_DIR/.cache/pip"`).
2. **Jobs del Pipeline:**
   - `lint:ruff`: Verifica linter (`ruff check app tests`) y formato (`ruff format --check app tests`).
   - `typecheck:mypy`: Instala dependencias del proyecto e invoca `mypy app tests` en modo estricto.
   - `test:pytest`: Ejecuta la suite de pruebas unitarias y de integración (`pytest tests/`).
   - `build:docker`: Construye y publica automáticamente la imagen definitiva multi-stage en el GitLab Container Registry (`$CI_REGISTRY_IMAGE:latest` y `$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA`) al hacer merge a `main` o sobre tags.
3. **Reglas de Ejecución (`rules`):**
   - Ejecución en eventos de Merge Request (`$CI_PIPELINE_SOURCE == "merge_request_event"`).
   - Ejecución en ramas de desarrollo (`$CI_COMMIT_BRANCH`), evitando ejecuciones duplicadas si existe una MR abierta.
4. **Criterios de Aceptación:**
   - Archivo `.gitlab-ci.yml` sintácticamente válido conforme al esquema de GitLab CI.
   - La suite de verificaciones local (`scripts/check.sh`) reproduce de manera idéntica los pasos que ejecutará el runner de CI.

---

## 3. Plan de Verificación

1. Validación de sintaxis YAML de `.gitlab-ci.yml` con parser estándar.
2. Comprobación de consistencia entre los comandos de `.gitlab-ci.yml` y `scripts/check.sh`.
3. Ejecución de `./scripts/check.sh` en local confirmando código de salida 0.
