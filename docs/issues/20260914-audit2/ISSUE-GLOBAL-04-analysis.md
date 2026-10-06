# Análisis Técnico: [GLOBAL-04] Ausencia Total de Pruebas de Integración End-to-End Reales

- **Issue:** [jg_agente#55](https://gitlab.com/javiergalvez-ia/jg_agente/-/work_items/55)
- **Severidad:** 🟠 ALTO
- **Ubicación:** `jg_dashboard/tests/`, `jg_agente/tests/`, `scripts/checks/`

---

## 1. Diagnóstico del Problema

### Causa Raíz
Las pruebas en `jg_dashboard` y `jg_agente` se desarrollaron de forma aislada utilizando simuladores (mocks) de red:
- En Laravel: `Http::fake()` interceptaba las llamadas hacia el agente, simulando respuestas HTTP estáticas sin calcular ni validar firmas HMAC reales ni enviar paquetes a través de la red TCP/IP de Docker.
- En FastAPI: `TestClient` ejecutaba la aplicación en memoria (`app`), omitiendo proxies, sockets reales, retardos de red, middlewares de infraestructura y el ciclo de vida de los contenedores Docker.

### Consecuencias
1. Incidentes graves de incompatibilidad (como GLOBAL-01 sobre generación de firmas y GLOBAL-02 sobre persistencia reversible del secreto) pasaron completamente inadvertidos durante los pipelines unitarios.
2. Incompatibilidades con versiones de navegadores y drivers (p. ej. geckodriver desactualizado o flags obsoletos de multiproceso en Firefox).
3. Problemas de configuración de puertos locales y redirecciones (Filament `APP_URL` vs puertos del host).

---

## 2. Estrategia de Solución

1. **Suite de Pruebas de Navegador Real (Selenium + Firefox):**
   - Ejecutar la suite sobre el stack Docker real levantado mediante `docker-compose.yml`.
   - Validar el flujo completo: autenticación real en Filament/Dashboard -> carga de consola web -> selección de agente -> cálculo real de firma HMAC-SHA256 en PHP -> envío a través de la red Docker -> recepción en Uvicorn/FastAPI -> validación de firma en Python -> ejecución del bucle LangGraph con herramientas reales -> retorno y renderizado en vivo en la interfaz.

2. **Orquestación y Scripts de Comprobación:**
   - Crear un script unificado `scripts/check.sh` que permita ejecutar de forma modular:
     - Todo el stack (`--all`).
     - Solo suites unitarias y linters (`--unit`).
     - Solo integración real E2E (`--e2e` o `--selenium`).
     - Filtro por proyectos específicos (`-p <proyecto>`).
   - Soportar modos interactivo (`--no-headless`) y CI/CD en segundo plano (`--headless`).
