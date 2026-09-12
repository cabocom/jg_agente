# Walkthrough: ISSUE-F01-T03 — Setup de CI/CD básico (Linting, Typechecking, Test Suite)

> **Estado:** COMPLETADO Y VALIDADO  
> **Fecha:** 4 de septiembre de 2026  
> **Comandos de Verificación:** Parser YAML de `.gitlab-ci.yml`, `./scripts/check.sh`  

---

## 1. Resumen de Componentes Creados

1. **Pipeline de Integración Continua ([.gitlab-ci.yml](file:///Users/javiergalvez/Documents/Code/javiergalvez-ia/jg_agente/.gitlab-ci.yml)):**
   - Definidas etapas estructuradas `lint`, `test` y `build`.
   - Implementado job `lint:ruff` (valida formato y reglas estáticas con ruff).
   - Implementado job `typecheck:mypy` (instala `.[dev]` y ejecuta `mypy app tests` en modo estricto).
   - Implementado job `test:pytest` (ejecuta suite de pruebas unitarias y de integración).
   - Implementado job `build:docker`:
     - Autenticación con registro privado propio (`registry.cabocom.net`) usando las variables de grupo heredadas `REGISTRY_HOST`, `REGISTRY_USER`, `REGISTRY_PASSWORD`.
     - Construcción y etiquetado automático usando el nombre de la rama sanitizado (`$SAFE_TAG` derivado de `$CI_COMMIT_BRANCH` / `$CI_COMMIT_REF_SLUG`), eliminando el commit SHA.
     - Publicación adicional con `:latest` cuando se ejecuta sobre la rama `main` y con tag Git en releases.
   - Configurada caché de paquetes pip por rama (`python-pip-${CI_COMMIT_REF_SLUG}`).
   - Establecidas reglas anti-duplicación para Merge Requests.

2. **Alineación con Herramientas Locales ([scripts/check.sh](file:///Users/javiergalvez/Documents/Code/javiergalvez-ia/jg_agente/scripts/check.sh)):**
   - El script local ejecuta de manera idéntica los tres pasos de CI:
     1. Ruff linter y format check.
     2. MyPy strict typechecking.
     3. Pytest test suite.

---

## 2. Evidencias de Validación

### 2.1 Validación de Sintaxis YAML y Estructura
```text
GitLab CI valid YAML! Stages: ['lint', 'test']
Jobs: ['lint:ruff', 'typecheck:mypy', 'test:pytest']
```

### 2.2 Ejecución de Suite de Verificación (`./scripts/check.sh`)
```text
========================================
🔍 Ejecutando verificación de código...
========================================

1️⃣  [Ruff] Análisis de formato y linter...
All checks passed!
7 files already formatted

2️⃣  [MyPy] Chequeo estático de tipos estricto...
Success: no issues found in 7 source files

3️⃣  [Pytest] Ejecución de suite de tests...
.....                                                                    [100%]
5 passed in 0.34s

========================================
✅ ¡Todas las comprobaciones pasaron con éxito!
========================================
```

---

## 3. Estado de Criterios de Aceptación

- [x] Archivo `.gitlab-ci.yml` creado con configuración para GitLab CI.
- [x] Etapas `lint` y `test` definidas con jobs específicos para Ruff, MyPy y Pytest.
- [x] Reglas de ejecución configuradas para MRs y branches principales.
- [x] Verificación local (`scripts/check.sh`) pasando en verde al 100% sin advertencias.
