# Análisis Técnico: ISSUE-F04-T01 — Definición de interfaz abstracta BasePlugin y ciclo de vida

> **Issue ID:** ISSUE-F04-T01  
> **Fase:** FASE 04 (CapabilityRegistry y Sistema de Plugins Core)  
> **Prioridad:** Critical  
> **Complejidad:** S  
> **Estado:** Implementado y Verificado  

---

## 1. Contexto y Objetivos

Para mantener el principio de **Agnosticismo Radical del Core**, `jg_agente` delega todo el conocimiento de dominio específico (DevOps, telefonía, clima, herramientas personalizadas) a módulos externos denominados **Plugins**.

El objetivo de este issue es establecer el contrato canónico abstracto:
1. Clase base abstracta `BasePlugin` que define la especificación obligatoria para cualquier plugin de la plataforma.
2. Contratos `@abstractmethod` estrictos para `get_plugin_metadata() -> PluginMetadata`, `register_tools() -> list[AgentTool]` y `register_engines() -> dict[str, BaseEngine]`.
3. Contrato abstracto `BaseEngine` para motores de dominio cognitivos o de infraestructura (observadores, planificadores, verificadores).
4. Modelo canónico Pydantic `PluginMetadata` con validación estricta de nombres slug, versiones y dependencias.
5. Hooks asíncronos de ciclo de vida (`startup`, `shutdown`, `health_check`) y soporte de gestor de contexto asíncrono (`async with plugin:`).
6. Hook opcional extensible `register_models() -> dict[str, type[BaseModel]]` para declarar esquemas Pydantic adicionales.

---

## 2. Reutilización y Adaptación (Código Origen)

- En `jg-ai-gateway/app/core/plugin.py`, existía una clase mínima `Plugin` con `startup` y `shutdown`.
- En `Devops60k`, los motores (`InfraDiscoveryEngine`, `VerificationEngine`) estaban fuertemente acoplados a infraestructura Docker/K8s sin una interfaz base formal.
- Se unificó y adaptó la especificación hacia un estándar moderno con tipado estricto Python 3.14, Pydantic v2 y soporte asíncrono nativo para el grafo LangGraph.

---

## 3. Decisiones de Diseño

1. **Inmutabilidad y Validación de Metadatos:**
   - `PluginMetadata` utiliza `frozen=True` y `extra="forbid"`, validando que el nombre sea un slug normalizado en minúsculas (`^[a-z0-9_-]+$`).
2. **Registro Tipado de Capacidades:**
   - `register_tools()` retorna una lista explícita de `AgentTool`, permitiendo que el futuro `CapabilityRegistry` indexe e inyecte validadores de seguridad automáticamente.
   - `register_engines()` retorna un diccionario mapeando roles o identificadores de motor a instancias de `BaseEngine`.
3. **Gestión de Recursos Asíncrona:**
   - Tanto `startup()` como `shutdown()` son asíncronos por diseño, garantizando compatibilidad con la inicialización concurrente en el lifespan de FastAPI y la liberación ordenada de conexiones de red.
   - Implementación de `__aenter__` y `__aexit__` para facilitar pruebas y ejecuciones acotadas en memoria.

---

## 4. Criterios de Aceptación Verificados

- [x] `BasePlugin` define contratos abstractos obligatorios para `register_tools()`, `register_engines()` y `get_plugin_metadata()`.
- [x] Tipado estricto verificado al 100% con MyPy sin errores.
- [x] Protección contra instanciación directa (`TypeError`).
- [x] Pruebas unitarias completas en `tests/test_base_plugin.py` verificando metadatos, herramientas, motores, modelos, ciclo de vida y gestor de contexto asíncrono.
- [x] Suite de 97 tests pasando con éxito en `./scripts/check.sh`.
