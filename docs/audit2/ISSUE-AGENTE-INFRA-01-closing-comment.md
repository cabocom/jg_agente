# Cierre de Issue: [AGENTE-INFRA-01] Ausencia de Workers en Uvicorn y Versión Menor no Fijada en Dockerfile

## Resolución
Se ha resuelto satisfactoriamente la ausencia de workers paralelos y la falta de fijación de versión menor en el contenedor Docker de `jg_agente` (Work item [#76](https://gitlab.com/javiergalvez-ia/jg_agente/-/work_items/76)):

1. **Fijación de Versión Menor Determinista:**
   - Fijada la imagen base a `python:3.12.6-slim` tanto en la etapa `builder` como en `runner` de `Dockerfile`.

2. **Parametrización de Workers en Uvicorn:**
   - Incorporada la variable de entorno `UVICORN_WORKERS=2` en la directiva `ENV` de `Dockerfile`.
   - Modificado `CMD` a `["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS:-2}"]` garantizando que el proceso conserve el PID 1 para la propagación adecuada de señales `SIGTERM`/`SIGINT`.
   - Añadido el atributo de configuración `UVICORN_WORKERS: int = Field(default=2, ge=1)` en `app/core/config.py`.
   - Declarada la variable `UVICORN_WORKERS: ${UVICORN_WORKERS:-2}` en los servicios de agente de `docker-compose.yml` (raíz) y `jg_agente/docker-compose.yml`.

3. **Verificación y Pruebas:**
   - Creada suite de pruebas unitarias `tests/test_dockerfile_configuration.py` validando estáticamente las directivas y la configuración de Settings.
   - Verificación estática con `ruff check`, `ruff format --check` y `mypy` (111 archivos verificados, 0 errores).
   - Verificación global con `bash check_unit.sh` (434 pruebas en `jg_agente` y 270 pruebas en `jg_dashboard` pasadas exitosamente).
