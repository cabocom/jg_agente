# Análisis Técnico: ISSUE-F01-T02 — Configuración de Dockerfile y Docker Compose para desarrollo local

> **Estado del Documento:** FINALIZADO  
> **Issue ID:** `ISSUE-F01-T02`  
> **Fase:** FASE 01 — Bootstrap, Documentación y Tooling  
> **Prioridad:** High  
> **Complejidad Estimada:** S  
> **Dependencias:** `ISSUE-F01-T01`  

---

## 1. Objetivo del Issue

Configurar el empaquetamiento en contenedores para `jg_agente` y la orquestación de desarrollo local con PostgreSQL mediante `docker-compose.yml`. Reutilizar el patrón de contenedor multi-stage probado en `Devops60k`, adaptándolo a la arquitectura desacoplada de `jg_agente`.

---

## 2. Requerimientos y Criterios de Aceptación

1. **Dockerfile Multi-Stage ([Dockerfile](../../../Dockerfile)):**
   - **Etapa 1 (Builder):** `python:3.12-slim` con compilación determinista e instalación de dependencias en `/install` mediante `pyproject.toml`.
   - **Etapa 2 (Runner):** Imagen final limpia, sin compiladores, ejecutando bajo usuario no-root `appuser:appgroup` (UID/GID 10001) para máxima seguridad (`security_opt`, `cap_drop: ALL`).
   - `HEALTHCHECK` activo contra el endpoint `/health`.
2. **Orquestación Local ([docker-compose.yml](../../../docker-compose.yml)):**
   - Servicio `jg_agente_postgres` con `postgres:16-alpine`, volumen persistente y healthcheck `pg_isready`.
   - Puerto del host configurable (`${POSTGRES_PORT:-5433}:5432`) para evitar conflictos con instancias existentes en 5432.
   - Servicio `jg_agente` enlazado con `depends_on` (condición `service_healthy`).
   - Red aislada `jg_agente_net`.
3. **Servidor Base y Verificación de Conectividad:**
   - [app/core/config.py](../../../app/core/config.py): Ajustes con Pydantic Settings para variables de entorno de PostgreSQL.
   - [app/main.py](../../../app/main.py): Endpoint `/health` con verificación real de conexión a PostgreSQL mediante `SELECT 1`.
4. **Criterio de Aceptación Principal:**
   - Los contenedores arrancan correctamente con `docker compose up -d`.
   - `jg_agente` responde en `/health` reportando `database: connected` y código HTTP 200.

---

## 3. Plan de Verificación

1. `docker compose build`: Construcción sin errores de la imagen multi-stage.
2. `docker compose up -d`: Inicio coordinado de base de datos y agente.
3. `docker compose ps`: Ambos contenedores en estado `Up (healthy)`.
4. `curl http://127.0.0.1:8001/health`: Respuesta con estado `healthy` y `database: connected`.
5. `./scripts/check.sh`: Validación de linter, tipos estáticos y tests unitarios.
