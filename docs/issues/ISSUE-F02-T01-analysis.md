# Análisis Técnico: ISSUE-F02-T01 — Implementación de contratos AgentInput y AgentOutput

> **Issue ID:** ISSUE-F02-T01  
> **Fase:** FASE 02 (Contratos y Modelos Core)  
> **Prioridad:** Critical  
> **Complejidad:** XS  
> **Estado:** Implementado y Verificado  

---

## 1. Contexto y Objetivos

En la arquitectura del ecosistema jG, `jg_agente` opera como el **Execution Plane**. Uno de sus principios de diseño cardinales es el **agnosticismo absoluto de protocolos de transporte e interfaces externas**.

El agente no debe tener conocimiento de si un estímulo proviene de una llamada telefónica SIP/Asterisk, un mensaje en Telegram/Slack, una llamada a un webhook o una invocación manual desde el panel de control (`jg_dashboard`).

Para materializar esta separación de responsabilidades, este issue implementa los contratos de datos canónicos:
- **`AgentInput`**: Estímulo estructurado de entrada para el ciclo cognitivo.
- **`AgentOutput`**: Respuesta normalizada del ciclo cognitivo, contemplando ejecución completada, fallo o interrupción por aprobación humana (HITL).
- **`UserContext`**: Metadatos de identidad, rol RBAC y permisos del usuario solicitante.
- **`ExecutionStatus`**: Enumeración estricta de estados de ejecución.

---

## 2. Reutilización y Adaptación (Código Origen)

Siguiendo la filosofía de refactorización:
- Se analizaron `RequestContext` e `IntentModel` en `Devops60k/app/models/state.py`.
- Se eliminaron las ataduras específicas a DevOps (anomalías de infraestructura, triggers propietarios) transformándolo en un esquema genérico.
- Se agregaron alias mediante `pydantic.AliasChoices` (`thread_id` / `session_id`, `prompt` / `message`, `response` / `answer`) garantizando interoperabilidad inmediata con los componentes legados y la especificación de `informe_arquitectonico_3.md` (AGT-004).

---

## 3. Decisiones Técnicas

1. **Pydantic V2 Estricto:**
   - Utilización de `ConfigDict(populate_by_name=True, extra="allow")` para permitir extensión controlada de metadatos contextuales sin romper serialización.
   - Validaciones de tipo nativas (`ge=0.0` en `execution_time_ms`, timestamps UTC con `datetime.UTC`).
2. **Uso de `StrEnum` (Python 3.12+):**
   - `ExecutionStatus` hereda de `StrEnum`, cumpliendo con las reglas modernas de Ruff y permitiendo serialización transparente como string en JSON.
3. **Ubicación en el Repositorio:**
   - Implementado en `app/models/io.py`.
   - Exportado en la interfaz pública `app/models/__init__.py`.

---

## 4. Criterios de Aceptación Verificados

- [x] Modelos `AgentInput` y `AgentOutput` definidos con tipado estricto en Pydantic V2.
- [x] Submodelo `UserContext` y enum `ExecutionStatus` implementados.
- [x] Soporte bidireccional para serialización/deserialización JSON.
- [x] Suite de tests unitarios exhaustiva en `tests/test_io_models.py`.
- [x] Pipeline local `./scripts/check.sh` pasando al 100% (Ruff, MyPy strict, Pytest).
