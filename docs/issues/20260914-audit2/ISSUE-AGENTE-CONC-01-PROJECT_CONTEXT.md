# Contexto del Proyecto: [AGENTE-CONC-01] Singletons de Seguridad sin Locks para Inicialización en Corrutinas

## Descripción del Entorno
- **Componente:** `jg_agente` (Security & Bootstrap Plane)
- **Capa Afectada:** Factorías Singleton de Seguridad (`app/security/guard.py`, `app/security/ssrf.py`, `app/security/audit.py`, `app/main.py`)
- **Severidad:** 🟡 MEDIO

## Contexto Operativo
`jg_agente` utiliza tres componentes nucleares de seguridad que deben operar como instancias únicas (singletons) en todo el proceso del agente:
1. **`SecurityGuard` (`get_security_guard()`):** Interceptor de ejecución para herramientas, verificación de permisos RBAC del llamador, mitigación de prompt injection y evaluación de riesgos HITL.
2. **`SSRFValidator` (`get_ssrf_validator()`):** Validador de mitigación contra Server-Side Request Forgery con DNS Pinning y resolución segura de IPs privadas o restringidas.
3. **`SecurityAuditLogger` (`get_security_audit_logger()` / `get_audit_logger()`):** Registrador de eventos de seguridad que gestiona el buffer circular en memoria y la persistencia no bloqueante en base de datos.

Estos componentes se instancian a demanda mediante factorías globales cuando los plugins se cargan, cuando las herramientas se invocan o cuando se ejecutan los grafos cognitivos.

## Problema Detectado
En la implementación inicial, cada factoría utilizaba un patrón de asignación perezosa sin sincronización:
```python
if _default_instance is None:
    _default_instance = Cls()
return _default_instance
```
Bajo condiciones de arranque rápido o ante ráfagas concurrentes de peticiones o corrutinas en el bucle de eventos (`asyncio` o hilos de trabajo):
1. Múltiples hilos o tareas evaluaban simultáneamente la condición `_default_instance is None` como verdadera.
2. Se instanciaban múltiples objetos independientes de `SecurityGuard`, `SSRFValidator` y `SecurityAuditLogger`.
3. Esto rompía la unicidad de estado:
   - Los registros de auditoría quedaban dispersos en distintos buffers en memoria.
   - Las cachés y configuraciones de `SSRFValidator` no se compartían.
   - `SecurityGuard` podía construirse con dependencias cruzadas desfasadas.
