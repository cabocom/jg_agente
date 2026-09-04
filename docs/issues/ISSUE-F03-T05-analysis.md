# Análisis Técnico: ISSUE-F03-T05 — Implementación de SecurityGuard para validación previa a ejecución de tools

> **Issue ID:** ISSUE-F03-T05  
> **Fase:** FASE 03 (Persistencia y Checkpointing)  
> **Prioridad:** Critical  
> **Complejidad:** M  
> **Estado:** Implementado y Verificado  

---

## 1. Contexto y Objetivos

En la arquitectura de `jg_agente`, el modelo de lenguaje (LLM) propone razonamientos y formulaciones de acciones, pero **jamás tiene acceso directo a ejecutar herramientas físicas sobre la infraestructura o la red**.
Es necesario interponer un interceptor central de seguridad (`SecurityGuard`) que actúe como un sandbox determinista y puerta de enlace previo a cualquier invocación de `tool.func`.

El objetivo de este issue es:
1. Interceptar toda solicitud de ejecución de `AgentTool`.
2. Validar que el llamador cuente con todos los `required_permissions` declarados por la herramienta.
3. Sanitizar los argumentos de entrada y bloquear inyecciones de comandos shell y Directory Traversal hacia rutas de sistema protegidas.
4. Para herramientas con capacidades de red (`makes_http_requests=True`), validar los destinos mediante `SSRFValidator`.
5. Evaluar el `RiskLevel`: si es `HIGH` o `CRITICAL`, emitir `REQUIRE_HUMAN_APPROVAL` para activar la pausa en el checkpointer LangGraph.
6. Auditar de manera inmutable cada decisión y ejecución a través de `SecurityAuditLogger`.

---

## 2. Reutilización y Adaptación (Código Origen)

- Se tomó la estructura básica de `Devops60k/app/tools/security/guard.py` y `policies.py`.
- Se adaptó de forma radical para garantizar el **agnosticismo del Core**: en vez de hardcodear componentes específicos de Kubernetes o Docker, `SecurityGuard` implementa reglas genéricas deterministas (permisos requeridos, inyecciones, directory traversal, SSRF por metadatos de tool, niveles de riesgo universales).
- Se integró directamente con `SecurityAuditLogger` (ISSUE-F03-T03) y `SSRFValidator` (ISSUE-F03-T04).

---

## 3. Decisiones de Diseño

1. **Pipeline de Decisión en `evaluate()`:**
   - **Paso 1 (Permisos):** Si faltan permisos requeridos por la tool → `DENY`.
   - **Paso 2 (Inyección / Traversal):** Si los argumentos contienen metacaracteres shell o rutas a `/etc`, `/proc`, etc. → `DENY`.
   - **Paso 3 (SSRF):** Si la tool hace peticiones HTTP y los argumentos contienen URLs/IPs prohibidas → `DENY`.
   - **Paso 4 (Riesgo / HITL):** Si el riesgo es `HIGH` o `CRITICAL` → `REQUIRE_HUMAN_APPROVAL`.
   - **Paso 5 (Autorización):** Si el riesgo es `LOW` o `MEDIUM` y pasó los filtros → `ALLOW`.
2. **Auditoría Sistemática:**
   - Toda evaluación (tanto `DENY`, `REQUIRE_HUMAN_APPROVAL` como `ALLOW`) genera un `SecurityEvaluationResult` registrado inmediatamente en `core_audit_records`.
3. **Control en `execute_tool()`:**
   - Ante `DENY` o `REQUIRE_HUMAN_APPROVAL`, la función subyacente `tool.func` **nunca se invoca**, retornando un `ToolResult` controlado con fallo o metadata de pausa HITL.
   - Ante `ALLOW`, sanitiza las entradas (`sanitize_arguments`), mide el tiempo de ejecución con precisión de microsegundos y audita el resultado final.

---

## 4. Criterios de Aceptación Verificados

- [x] Bloqueo de ejecuciones cuando el llamador carece de permisos requeridos.
- [x] Bloqueo determinista ante inyección de comandos shell y directory traversal.
- [x] Bloqueo ante violación de políticas SSRF en herramientas de red.
- [x] Puerta HITL (`REQUIRE_HUMAN_APPROVAL`) para herramientas de riesgo alto y crítico.
- [x] Sanitización efectiva de entradas previo a la invocación de `func`.
- [x] Registro inmutable en `SecurityAuditLogger` tanto de evaluaciones como de ejecuciones físicas.
- [x] 90 tests pasando con éxito (100% verde en Ruff, MyPy estricto y Pytest).
