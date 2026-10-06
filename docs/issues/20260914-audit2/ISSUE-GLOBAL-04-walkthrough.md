# Walkthrough Técnico: [GLOBAL-04] Ausencia Total de Pruebas de Integración End-to-End Reales

## Resumen de la Intervención

Se implementó y estabilizó una suite completa de pruebas End-to-End (E2E) con Selenium y Firefox contra el stack Docker en vivo, acompañada de un orquestador bash unificado (`scripts/check.sh`) que permite ejecutar verificaciones unitarias, de integración o ambas de forma parametrizada y filtrable por proyecto.

---

## Componentes y Archivos Clave

### 1. Suite E2E con Selenium (`scripts/checks/e2e_dashboard/`)
- **`test_web_console_e2e.py`:**
  - Automatización del navegador Firefox mediante geckodriver.
  - Validación de 8 etapas funcionales completas:
    1. Autenticación en `/admin/login` y redirección controlada.
    2. Inspección de cabecera, navegación lateral, permisos RBAC y pie institucional.
    3. Selector interactivo de temas visuales (Claro y Oscuro).
    4. Modal de autogestión de perfil de usuario y credenciales.
    5. Catálogo de agentes y acción rápida "Lanzar Ejecución".
    6. Disparo y ejecución en vivo de **Agente Conversacional** (a0000000-0000-0000-0000-000000000001) con observación de saltos LangGraph (`OBSERVING`, `EXECUTING`, `COMPLETED`) y validación de palabras clave.
    7. Disparo y ejecución en vivo de **Agente DevOps** (a0000000-0000-0000-0000-000000000002) verificando contenedores Docker a través del socket proxy seguro.
    8. Historial de ejecuciones, filtros por agente, filtros temporales y apertura del modal de traza profunda.
  - Soporte de argumentos `--headless` y `--no-headless`.
  - Eliminación de opciones deprecadas (`dom.ipc.processCount`, `browser.tabs.remote.autostart`) para compatibilidad plena con Firefox moderno.

### 2. Comando Unificado de Verificación (`scripts/check.sh`)
- Orquestador maestro con soporte para:
  - `--all`: Ejecución completa de pruebas unitarias + E2E.
  - `--unit`: Ejecución exclusiva de pruebas unitarias y análisis estático (Ruff, MyPy, Pest/PHPUnit, Pytest).
  - `--e2e` / `--selenium`: Ejecución exclusiva de pruebas web Selenium.
  - `-p, --project <nombre>`: Filtrado granular por proyecto (`jg_agente`, `jg_dashboard`, `jg_agente_sdk`, `jg_plugin_datosgob`).
  - Detección inteligente para proyectos de backend/librería sin interfaz visual cuando se solicita E2E.

### 3. Sincronización e Infraestructura
- **`docker-compose.yml` & `.env`:** Reconfiguración del puerto del Dashboard a `8003` para evitar colisiones con proxies locales o túneles SSH.
- **`scripts/core/restart_services.sh`:** Verificación de salud adaptativa según `${DASHBOARD_PORT:-8003}`.
- **`scripts/help.sh` & `scripts/README.md`:** Documentación actualizada del catálogo de comandos.

---

## Resultados de Verificación

```bash
# 1. Verificación unitaria consolidada
./scripts/check.sh --unit
# ✅ jg_agente:           PASÓ (Ruff, MyPy y 114 Pytest)
# ✅ jg_dashboard:        PASÓ (284 tests Pest)
# ✅ jg_agente_sdk:       PASÓ (47 tests Pytest)
# ✅ jg_plugin_datosgob:  PASÓ (20 tests Pytest)

# 2. Verificación E2E Selenium completa
./scripts/check.sh --e2e --headless
# ✅ Servicios Docker:    REINICIADOS Y SALUDABLES
# ✅ Web E2E Selenium:    PASÓ AL 100% (Firefox real)
```
