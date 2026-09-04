# Análisis Técnico: ISSUE-F04-T04 — Validación en boot del agente contra CapabilityRegistry

> **Issue ID:** ISSUE-F04-T04  
> **Fase:** FASE 04 (CapabilityRegistry y Sistema de Plugins Core)  
> **Prioridad:** High  
> **Complejidad:** S  
> **Estado:** Implementado y Verificado  

---

## 1. Contexto y Objetivos

Para evitar que un agente arranque en un estado parcialmente configurado, degradado o vulnerable (por ejemplo, careciendo de un motor planificador o herramientas esenciales exigidas por su perfil), se necesita una función determinista de verificación de integridad previa al inicio de FastAPI.

El objetivo de este issue es:
1. Desarrollar `app/core/boot.py` con la excepción `BootIntegrityError` y la función `validate_boot_capabilities()`.
2. Validar que todos los plugins esenciales (`settings.REQUIRED_PLUGINS`) y herramientas obligatorias (`settings.REQUIRED_TOOLS`) se encuentren debidamente registrados en el `CapabilityRegistry`.
3. Validar la presencia de motores cognitivos esenciales (`PlannerEngine`, `ObserverEngine`, `VerifierEngine`) si el perfil del agente los declara obligatorios.
4. Validar la integridad interna de herramientas registradas (`callable(tool.func)`, categoría presente).
5. Orquestar el arranque con `init_agent_capabilities()`, integrándolo en el `lifespan` de FastAPI en `app/main.py`.
6. Exponer el endpoint público `GET /capabilities` reflejando el catálogo consolidado de capacidades del agente.

---

## 2. Reutilización y Adaptación (Código Origen)

- En los proyectos precedentes (`Devops60k` y `jg-ai-gateway`), el arranque no validaba formalmente la integridad de componentes ni abortaba el proceso ante ausencia de herramientas, lo que derivaba en fallos en tiempo de ejecución durante la primera interacción del usuario.
- En `jg_agente`, se adopta el principio *fail-fast*: cualquier discrepancia entre el perfil esperado y las capacidades registradas aborta el boot con un mensaje de error descriptivo antes de exponer endpoints REST.

---

## 3. Decisiones de Diseño

1. **Excepción Explícita `BootIntegrityError`:**
   - Permite diferenciar claramente un error de configuración o falta de capacidades de un error de infraestructura de base de datos o colisión de nombres (`BootConflictError`).
2. **Desacoplamiento de Perfiles vía Configuración:**
   - Los requerimientos de perfil se parametrizan en `Settings` (`REQUIRED_PLUGINS`, `REQUIRED_TOOLS`, `REQUIRE_PLANNER`, `REQUIRE_OBSERVER`, `REQUIRE_VERIFIER`), permitiendo que el mismo binario de `jg_agente` opere como agente conversacional ligero o como agente DevOps complejo con solo variar variables de entorno.
3. **Integración en Lifespan:**
   - La validación ocurre dentro del gestor asíncrono de FastAPI antes de ceder el control al servidor HTTP (`yield`), asegurando que ningún cliente pueda enviar peticiones a un agente no verificado.

---

## 4. Criterios de Aceptación Verificados

- [x] El agente valida el registro de capacidades y aborta el arranque con mensaje descriptivo si faltan componentes esenciales o hay colisiones.
- [x] Verificado el aborto ante plugin esencial ausente.
- [x] Verificado el aborto ante herramienta obligatoria ausente.
- [x] Verificado el aborto ante motor cognitivo exigido ausente.
- [x] Verificada la propagación limpia de `BootConflictError`.
- [x] Endpoint `GET /capabilities` operativo y verificado en `app/main.py`.
- [x] 127 tests pasando con éxito (100% verde en Ruff, MyPy estricto y Pytest).
