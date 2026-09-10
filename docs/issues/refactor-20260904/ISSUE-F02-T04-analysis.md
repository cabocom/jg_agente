# Análisis Técnico: ISSUE-F02-T04 — Definición del estado global del agente (AgentState)

> **Issue ID:** ISSUE-F02-T04  
> **Fase:** FASE 02 (Contratos y Modelos Core)  
> **Prioridad:** Critical  
> **Complejidad:** S  
> **Estado:** Implementado y Verificado  

---

## 1. Contexto y Objetivos

En la arquitectura de `jg_agente`, el motor de orquestación se basa en **LangGraph**. El estado global que fluye entre los nodos del grafo cognitivo debe cumplir simultáneamente tres principios arquitectónicos fundamentales:
1. **Agnosticismo Radical:** El Core desconoce conceptos específicos de dominio como contenedores, servidores, particiones de disco o canales telefónicos. No puede contener referencias a `InfraSnapshot`, `Docker`, `K8s` ni alertas propietarias.
2. **Extensibilidad de Entorno mediante `environment_snapshot`:** La información descubierta o monitoreada sobre el entorno se almacena bajo `environment_snapshot: Optional[dict[str, Any]]`, permitiendo que cualquier plugin (conversacional, devops, financiero) hidrate o serialice sus propios modelos tipados sin alterar el esquema del grafo central.
3. **Compatibilidad Nativa con LangGraph:** Integración del canal `messages` utilizando el reducer oficial `add_messages` (para conversaciones multi-turno) y el reducer `append_reducer` para trazas acumulativas (`audit_trail`, `execution_records`, `errors`).

---

## 2. Reutilización y Adaptación (Código Origen)

- Se extrajeron y adaptaron los patrones troncales de `Devops60k/app/models/state.py` (`append_reducer`, `IntentModel`, `ExecutionPlan`, `PlanStep`, `ApprovalRecord`, `StepExecutionRecord`, `AuditRecord`, `ExecutionError`).
- Se eliminaron completamente todos los acoplamientos a DevOps presentes en `Devops60kState` (`InfraSnapshot`, `Incident`, `HealingAttemptRecord`, métricas fijas de infraestructura).
- Se sustituyó `infra_snapshot` por `environment_snapshot: Optional[dict[str, Any]]` conforme al Informe Arquitectónico 3 y `PROJECT_CONTEXT.md`.
- Se incorporó soporte nativo de mensajes con `langchain_core.messages.BaseMessage` y `langgraph.graph.message.add_messages`.

---

## 3. Decisiones de Diseño

1. **Uso de `TypedDict(total=False)` para `AgentState`:**
   - Permite que los nodos del grafo devuelvan únicamente las claves mutadas (actualizaciones delta) sin necesidad de reconstruir el diccionario completo en cada transición.
2. **Modelos Operacionales Pydantic V2:**
   - Submodelos fuertemente tipados (`IntentModel`, `PlanStep`, `ExecutionPlan`, `ApprovalRecord`, etc.) para estructurar la cognición del agente con validaciones y serialización JSON.
3. **Enums Canónicos con `StrEnum`:**
   - `AgentExecutionStatus`, `ApprovalStatus`, `StepStatus`, `VerificationStatus`.
4. **Ubicación en el Repositorio:**
   - Archivo `app/models/state.py`.
   - Exportación de la interfaz pública en `app/models/__init__.py`.

---

## 4. Criterios de Aceptación Verificados

- [x] `AgentState` definido como `TypedDict` conteniendo `messages`, `intent`, `plan`, `status`, `environment_snapshot` (Optional[dict]) y `audit_trail`.
- [x] Sin referencias ni dependencias de DevOps o infraestructura.
- [x] Reducers de LangGraph (`add_messages` y `append_reducer`) verificados en flujos de ejecución reales.
- [x] 10 tests unitarios específicos pasando en `tests/test_agent_state.py` (totalizando 44 tests en el repositorio).
- [x] Script `./scripts/check.sh` pasando al 100% (Ruff OK, MyPy estricto OK, Pytest OK).
