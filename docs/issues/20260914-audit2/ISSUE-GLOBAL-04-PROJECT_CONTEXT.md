# Project Context: [GLOBAL-04] Ausencia Total de Pruebas de Integración End-to-End Reales

## Identificadores y Metadatos

- **GitLab Issue:** [jg_agente#55](https://gitlab.com/javiergalvez-ia/jg_agente/-/work_items/55)
- **Severidad:** 🟠 ALTO
- **Componentes Afectados:** Ecosistema completo (`jg_agente`, `jg_dashboard`, scripts de automatización e infraestructura Docker)

---

## Contexto y Alcance del Defecto

A pesar de contar con amplias suites de pruebas unitarias y de integración en memoria (600+ pruebas combinadas con mocks en Guzzle, HttpClient y TestClient), existía un vacío crítico de pruebas que levantaran el stack real para verificar:
1. La comunicación HTTP real firmada con HMAC-SHA256 entre `jg_dashboard` y `jg_agente`.
2. La resolución cognitiva en vivo de LangGraph ejecutando herramientas reales.
3. La interacción con la interfaz web y la autogestión de perfil, autenticación, catálogo y trazas en tiempo real.
4. La prevención de regresiones de red, variables de entorno, puertos y middlewares.

---

## Componentes Involucrados

1. **Suite End-to-End con Selenium (`scripts/checks/e2e_dashboard/`):**
   - `test_web_console_e2e.py`: Casos de prueba automatizados con Firefox y geckodriver (autenticación, catálogo, pasarela de disparo en tiempo real, saltos cognitivos, historial y modal de traza).
   - `run_e2e.sh`: Lanzador directo con aislamiento en virtualenv dedicado.
2. **Orquestación de Servicios y Pruebas Web (`scripts/checks/`):**
   - `check_web.sh`: Sincronización y reinicio de contenedores Docker (`scripts/core/restart_services.sh`) y ejecución de la suite Selenium.
3. **Comando Unificado de Calidad (`scripts/check.sh`):**
   - Orquestador integral con opciones `--all`, `--unit`, `--e2e` y filtrado por proyecto (`-p, --project`).
4. **Infraestructura (`docker-compose.yml`, `.env`):**
   - Mapeo de puertos desacoplado (puerto 8003 para Dashboard) y resolución de colisiones en entornos locales.
