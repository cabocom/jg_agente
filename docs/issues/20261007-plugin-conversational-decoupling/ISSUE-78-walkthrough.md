# Walkthrough: [jg_agente#78] Desacoplamiento y Extracción de jg_plugin_conversational

## 1. Resumen de Cambios Realizados

1. **Nuevo Subrepositorio Independiente `jg_plugin_conversational`:**
   - Ubicación: `/Users/javiergalvez/Documents/Code/javiergalvez-ia/jg_plugin_conversational`
   - Git remote: `git@gitlab.com:javiergalvez-ia/jg_plugin_conversational.git`
   - Archivos de configuración: `.gitignore`, `pyproject.toml`, `.gitlab-ci.yml`, `LICENSE`, `README.md`, `PROJECT_CONTEXT.md`, `install.sh`, `scripts/check.sh`.
2. **Paquete Python `jg_plugin_conversational`:**
   - `__init__.py`: Exporta `ConversationalPlugin`, `PLUGIN_CLASS`, herramientas y esquemas.
   - `plugin.py`: Implementa `BasePlugin` con metadatos canónicos y ciclo de vida asíncrono.
   - `weather.py`: Herramienta `get_weather` (`WeatherArgs`, Azure Maps + simulación determinista).
   - `news.py`: Herramienta `get_news` (`NewsArgs`, Europa Press RSS + simulación determinista).
   - `ssrf_guard.py`: Helper autónomo de validación de URLs y protección anti-SSRF sin dependencias del core.
3. **Suite de Tests Unitarios Autónoma (`tests/`):**
   - `test_plugin.py`: Valida ciclo de vida, introspección, aislamiento estricto y compatibilidad con `MockPluginRunner`.
   - `test_weather_tool.py`: Valida `WeatherArgs`, validación de coordenadas/dirección, mocks de Azure Maps y fallbacks.
   - `test_news_tool.py`: Valida `NewsArgs`, parseo XML con `defusedxml`, bloqueo XXE y mitigación anti-SSRF.
4. **Limpieza en `jg_agente`:**
   - Eliminado `jg_agente/plugins/jg_plugin_conversational/`.
   - Actualizado `jg_agente/pyproject.toml` (eliminadas rutas residuales en `pythonpath` e `isort`).
5. **Integración en Entorno Global:**
   - Actualizado `.gitignore` de raíz para ignorar `/jg_plugin_conversational/`.
   - Actualizado `docker-compose.yml` para montar `./jg_plugin_conversational/jg_plugin_conversational:/app/plugins/jg_plugin_conversational:ro`.
   - Actualizado `scripts/check.sh` con target `-p jg_plugin_conversational` (alias `conversacional`).
   - Actualizado `scripts/plugins/check_all.sh` y documentación del ecosistema (`docs/PLUGINS.md`, `docs/OVERVIEW.md`, `README.md`, `PROJECT_CONTEXT.md`).

## 2. Validación de Criterios de Aceptación (DoD)

```bash
# 1. Cero referencias a app.* en el nuevo paquete
grep -rn "from app\." jg_plugin_conversational/
# Resultado: VACÍO (0 incidencias)

# 2. Ejecución aislada de linters y tests unitarios
cd jg_plugin_conversational && ./scripts/check.sh
# Resultado: Ruff check OK, Ruff format OK, 25 tests passed en 0.20s

# 3. Verificación de plugins consolidada
bash scripts/plugins/check_all.sh
# Resultado: 1/3 datosgob OK (20 passed), 2/3 conversational OK (25 passed), 3/3 devops OK (50 passed).

# 4. Verificación del target en scripts/check.sh
./scripts/check.sh --unit -p jg_plugin_conversational
# Resultado: PASÓ con éxito
```
