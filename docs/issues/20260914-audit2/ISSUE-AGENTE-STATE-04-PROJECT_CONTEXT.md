# Contexto del Proyecto: [AGENTE-STATE-04] Fuga de Memoria por Crecimiento Ilimitado en SecurityAuditLogger

## Descripción del Entorno
- **Componente:** `jg_agente` (Security & Audit Plane)
- **Capa Afectada:** Auditoría de Seguridad en Memoria (`app/security/audit.py`, `app/core/config.py`)
- **Estructura Afectada:** Historial en memoria `self._history` en `SecurityAuditLogger`
- **Severidad:** 🟡 MEDIO

## Contexto Operativo
`jg_agente` incorpora un componente centralizado de auditoría de seguridad (`SecurityAuditLogger`) instanciado como singleton accesible mediante `get_audit_logger()`.
Este registrador es invocado de manera continua a lo largo del ciclo de vida del agente:
1. Inspección de riesgos y validación de prompts (Prompt Injection, System Override).
2. Verificación de tool calls y políticas RBAC / guardrails.
3. Evaluación y resolución de acciones Human-In-The-Loop (HITL).
4. Errores y eventos de degradación operativa.

Cada evento genera una instancia de `AuditRecord` que se registra con `record_event()`.

## Problema Detectado
En la implementación original:
1. `self._history: list[AuditRecord] = []` acumulaba indefinidamente todos los registros de auditoría en una lista de Python sin ningún límite superior ni política de expiración o truncado.
2. Dado que el servicio `jg_agente` está diseñado como un proceso daemon asíncrono de larga duración (semanas o meses en contenedores de producción), la lista de registros en memoria crecía monótonamente con cada interacción.
3. A medida que el agente procesaba miles de ejecuciones y comprobaciones de seguridad, el consumo de memoria RAM aumentaba sin freno, culminando inevitablemente en fallos por falta de memoria (Out Of Memory / OOM kill) del contenedor en producción.
