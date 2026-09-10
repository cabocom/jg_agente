# Actualización de Contexto de Proyecto: ISSUE-F08-T03

## Módulo Afectado
- `jg_agente`: Execution Plane (Motor Autónomo de Ejecución).
- Componentes: `app.core.config`, `app.core.heartbeat`, `app.main`, `tests.test_heartbeat_service`.

## Contexto de la Decisión Arquitectónica
- Se completa la **Fase 08 al 100%**: el agente ya dispone de ciclo completo de vida con respecto al Dashboard:
  1. Registro Zero-Trust mediante bootstrap token (F08-T01).
  2. Persistencia y recarga de credencial permanente con permisos 0600 y validación activa en boot (F08-T02).
  3. Bucle periódico de heartbeat con telemetría de salud, memoria y capacidades (F08-T03).
- **Aislamiento y Resiliencia:** El bucle de heartbeat es una tarea en segundo plano no bloqueante. Ante cualquier degradación de red o indisponibilidad del Dashboard, el agente sigue operando de forma autónoma sin interrupción de sus capacidades cognitivas ni terminación del proceso.
- **Portabilidad de Métricas:** La medición de consumo de memoria de proceso vía `resource.getrusage` se adapta dinámicamente entre Linux (kB) y Darwin/macOS (bytes) para evitar distorsiones en las métricas expuestas.

## Estado Post-Issue
- Versión de contexto: `2.25.0`
- Fases 01 a 08 completadas al 100%.
- Preparado para la fase de plugins (`jg_plugin_*`) y la orquestación coordinada de servicios con Docker Compose.
