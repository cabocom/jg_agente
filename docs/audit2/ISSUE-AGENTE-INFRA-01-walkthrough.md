# Walkthrough Técnico: [AGENTE-INFRA-01] Ausencia de Workers en Uvicorn y Versión Menor no Fijada en Dockerfile

## Resumen de Cambios Aplicados

### 1. Dockerfile ([`Dockerfile`](file:///Users/javiergalvez/Documents/Code/javiergalvez-ia/jg_agente/Dockerfile))
- Actualizadas las imágenes base de ambas etapas:
  ```dockerfile
  FROM python:3.12.6-slim AS builder
  ...
  FROM python:3.12.6-slim AS runner
  ```
- Añadida la variable de entorno `UVICORN_WORKERS=2` a la directiva `ENV`.
- Actualizado el comando de arranque para usar `exec` y la parametrización de workers:
  ```dockerfile
  CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS:-2}"]
  ```

### 2. Configuración Centralizada ([`app/core/config.py`](file:///Users/javiergalvez/Documents/Code/javiergalvez-ia/jg_agente/app/core/config.py))
- Añadida la configuración en `Settings`:
  ```python
  UVICORN_WORKERS: int = Field(
      default=2, ge=1, description="Número de workers paralelos para el servidor Uvicorn"
  )
  ```

### 3. Docker Compose
- **[`jg_agente/docker-compose.yml`](file:///Users/javiergalvez/Documents/Code/javiergalvez-ia/jg_agente/docker-compose.yml):** Añadido `UVICORN_WORKERS: ${UVICORN_WORKERS:-2}` en el servicio `jg_agente`.
- **[`docker-compose.yml`](file:///Users/javiergalvez/Documents/Code/javiergalvez-ia/docker-compose.yml):** Añadido `UVICORN_WORKERS: ${UVICORN_WORKERS:-2}` en `jg_agente_conversacional` y `jg_agente_devops`.

### 4. Pruebas Automatizadas ([`tests/test_dockerfile_configuration.py`](file:///Users/javiergalvez/Documents/Code/javiergalvez-ia/jg_agente/tests/test_dockerfile_configuration.py))
- Verificación estática de que `Dockerfile` fija `python:3.12.6-slim` en `builder` y `runner`.
- Verificación de que `UVICORN_WORKERS` está presente en `ENV` y parametrizada con `--workers` y `exec` en `CMD`.
- Verificación de que `Settings` expone `UVICORN_WORKERS` con validación mayor o igual a 1.

### 5. Impacto Operacional
- Compilaciones 100% reproducibles e inmunes a actualizaciones no deseadas de imágenes base.
- Multiplicación del rendimiento de concurrencia y aprovechamiento multicore en producción.
- Apagado ordenado limpio al recibir `SIGTERM` sin esperas de forzado de kill.
