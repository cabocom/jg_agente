# 02. Grafo Cognitivo y Máquina de Estados (`jg_agente`)

[← Volver al README](../README.md) | [← 01. Arquitectura](01_architecture.md) | [03. Seguridad →](03_security_sandboxing.md)

---

## 1. Topología Ensamblada Dinámicamente

`GraphBuilder` (`app/core/graph.py`) implementa el principio de **Agnosticismo Radical del Core**. La topología de LangGraph no es una estructura fija ni cableada, sino que se compila en el arranque inspeccionando el `CapabilityRegistry`:

```text
                  [Entrada: AgentInput]
                            │
                            ▼
               ┌───────────────────────────┐
               │   1. Telemetría (observe) │ ──► (Condicional: si hay ObserverEngine)
               └─────────────┬─────────────┘
                             ▼
               ┌───────────────────────────┐
         ┌───► │  2. Inferencia (reason)   │ ◄─────────────────────────────────────────┐
         │     └─────────────┬─────────────┘                                           │
         │                   ▼                                                         │
         │     ┌───────────────────────────┐                                           │
         │     │ 3. Formulación Plan (plan)│ ──► (Condicional: si hay PlannerEngine)   │
         │     └─────────────┬─────────────┘                                           │
         │                   ▼                                                         │
         │     ┌───────────────────────────┐                                           │
         │     │  4. Riesgo (risk_assess)  │ ──► (Condicional: Tools HIGH/CRITICAL)    │
         │     └─────────────┬─────────────┘                                           │
         │                   │                                                         │
         │      ¿Riesgo >= HIGH o Mutación?                                            │
         │     ┌─────────────┴─────────────┐                                           │
         │[SÍ] ▼                           ▼ [NO]                                      │
         │ ┌───────────────────┐           │                                           │
         │ │ Pausa Checkpoint  │           │                                           │
         │ │ (human_approval)  │           │                                           │
         │ └─────────┬─────────┘           │                                           │
         │           │ (Resume HITL)       │                                           │
         │           └─────────────┬───────┘                                           │
         │                         ▼                                                   │
         │     ┌───────────────────────────┐                                           │
         │     │  5. Ejecución (execute)   │ ──► (Sandbox + Timeouts + SecurityGuard)  │
         │     └─────────────┬─────────────┘                                           │
         │                   ▼                                                         │
         │     ┌───────────────────────────┐                                           │
         │     │ 6. Verificación (verify)  │ ──► (Condicional: si hay VerifierEngine)  │
         │     └─────────────┬─────────────┘                                           │
         │                   │                                                         │
         │            ¿Fallo detectado?                                                │
         │     ┌─────────────┴─────────────┐                                           │
         │[SÍ] ▼                           ▼ [NO]                                      │
         │ ┌───────────────────┐           │                                           │
         │ │  Compensación     │           │                                           │
         │ │    (rollback)     │           │                                           │
         │ └─────────┬─────────┘           │                                           │
         │           └─────────────┬───────┘                                           │
         │                         ▼                                                   │
         │     ┌───────────────────────────┐                                           │
         │     │ 7. Evaluación (evaluate)  │ ──► (Obligatorio: Verificación semántica) │
         │     └─────────────┬─────────────┘                                           │
         │                   │                                                         │
         │        ¿Objetivo alcanzado?                                                 │
         │        ├── Needs More Info & iter < 3 ──────────────────────────────────────┘
         │        └── Satisfecho / Fallo / iter >= 3
         │                   │
         │                   ▼
         │     ┌───────────────────────────┐
         │     │ 8. Conclusión (conclude)  │ ──► Generación de salida AgentOutput
         │     └─────────────┬─────────────┘
         │                   ▼
         └────────────────► [END]
```

## 2. Nodos del Grafo

| Nodo | Obligatorio / Condicional | Función Técnica | Archivo de Origen |
| :--- | :--- | :--- | :--- |
| **`observe`** | Condicional | Captura telemetría y estado del entorno delegando en `ObserverEngine`. | `app/nodes/observe.py` |
| **`reason`** | Obligatorio | Razonamiento LLM, enlace de herramientas (*tool binding*) y extracción de intención (`IntentModel`). | `app/nodes/reason.py` |
| **`plan`** | Condicional | Descompone la intención en pasos estructurados (`PlanStep`) con asignación de herramientas y dependencias. | `app/nodes/plan.py` |
| **`risk_assess`** | Condicional | Valida políticas preventivas antes de interactuar con el entorno. Clasifica riesgos `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`. | `app/nodes/risk_assess.py` |
| **`human_approval`**| Condicional | Invoca `langgraph.types.interrupt()` pausando la ejecución de mutaciones de alto riesgo para revisión humana. | `app/nodes/human_approval.py`|
| **`execute`** | Obligatorio | Invoca herramientas a través de `SecurityGuard.execute_tool()` con límites temporales duros (`timeout_sec`). | `app/nodes/execute.py` |
| **`verify`** | Condicional | Valida post-condiciones y estado del entorno delegando en `VerifierEngine`. | `app/nodes/verify.py` |
| **`rollback`** | Condicional | Ejecuta funciones compensatorias (`tool.rollback_func`) en orden inverso ante fallos. | `app/nodes/rollback.py` |
| **`evaluate`** | Obligatorio | Evalúa semánticamente si la evidencia recabada satisface el objetivo original (`GoalStatus`). | `app/nodes/evaluate.py` |
| **`conclude`** | Obligatorio | Consolida la respuesta final estructurada en `AgentOutput` y actualiza la auditoría. | `app/nodes/conclude.py` |

## 3. Protocolo de Interrupción y Reanudación HITL

El nodo `human_approval` implementa el patrón de pausa nativo de LangGraph:

1. **Pausa:** Al detectar una operación de alto riesgo no autorizada previamente, ejecuta:
   ```python
   decision = interrupt({
       "action": "human_approval_required",
       "execution_id": execution_id,
       "thread_id": thread_id,
       "risk_assessment": risk_info,
       "plan": plan_info,
       "message": "Operación de alto riesgo detectada. Se requiere autorización humana."
   })
   ```
   LangGraph suspende la máquina de estados levantando `GraphInterrupt` y persistiendo el snapshot en PostgreSQL.

2. **Reanudación:** Cuando el operador envía la decisión desde el Dashboard (`POST /executions/{thread_id}/approve` o `reject`), el runtime reanuda la ejecución inyectando:
   ```python
   command = Command(resume={
       "approved": True,
       "status": "approved",
       "approver": "operador@empresa.com",
       "notes": "Autorizado tras validar plan"
   })
   final_state = await graph.ainvoke(command, config=config)
   ```

### 3.1 Autorización Granular por Pasos y Herramientas
La resolución HITL no es un permiso en blanco. El estado del agente y el nodo ejecutor ([app/nodes/execute.py](../app/nodes/execute.py)) gestionan autorización restrictiva:
- **`approved_step_ids`:** Identificadores únicos de los pasos del plan aprobados explícitamente.
- **`approved_tool_names`:** Nombres de las herramientas que el operador autorizó ejecutar.
- **Validación en Ejecución:** Al reanudarse el grafo, `SecurityGuard` comprueba que la operación entrante coincida con los identificadores o herramientas autorizadas. Si el LLM intentara intercalar una mutación no aprobada, se bloquea nuevamente garantizando el principio de mínimo privilegio.

---

## 4. Mecanismo de Compensación Transaccional (`rollback_node`)

Implementado en [app/nodes/rollback.py](../app/nodes/rollback.py), revierte de forma determinista las acciones que modificaron el entorno cuando el motor de verificación detecta un fallo (`VerificationStatus.FAIL` o `DEGRADED`):

1. **Orden Cronológico Inverso:**
   Itera sobre `execution_records` en orden estrictamente inverso (`reversed(records)`), asegurando que la última acción ejecutada sea la primera en ser compensada (política LIFO transaccional).

2. **Inyección de `rollback_context`:**
   Al ejecutarse cualquier herramienta reversible (`reversible=True`), esta devuelve un diccionario estructurado `ToolResult.rollback_context` (con snapshots de estado previo, IDs de recursos creados o valores originales). El nodo de compensación recupera dicho contexto y lo pasa a:
   ```python
   res = tool.rollback(rec.rollback_context)
   tool_res = await ensure_awaited(res)
   ```

3. **Dualidad Asíncrona:**
   Soporta tanto funciones de compensación síncronas como corutinas asíncronas (`ensure_awaited`), registrando los resultados individuales en `rollback_records` y emitiendo un evento inmutable `rollback_completed` o `rollback_failed` en la auditoría.

---

## 5. Autoconciencia de Capacidades Ausentes (`evaluate_node`)

En [app/nodes/evaluate.py](../app/nodes/evaluate.py), el evaluador cognitivo incorpora detección proactiva de suficiencia funcional (*Capability-Awareness*):

1. **Contraste contra `CapabilityRegistry`:**
   El nodo analiza la petición del usuario y la compara con el catálogo de herramientas realmente disponibles en el agente (`tool_names_available`).

2. **Detección de Bloqueo (`GoalStatus.BLOCKED_MISSING_CAPABILITY`):**
   Si el LLM determina que para satisfacer la petición se requiere una capacidad inexistente en el runtime (por ejemplo, el usuario solicita inspeccionar logs de Docker pero el agente no tiene cargado `jg_plugin_devops`), no entra en bucles de reintento:
   - Emite `GoalStatus.BLOCKED_MISSING_CAPABILITY`.
   - Popula `missing_capabilities: list[str]` con las herramientas o integraciones ausentes.
   - Genera una sugerencia de acción alternativa (`suggested_next_action`).
   - Enruta inmediatamente hacia `conclude` para informar de forma transparente al usuario sin alucinar resultados.

---

## 6. Síntesis Defensiva en `conclude_node`

El nodo terminal [app/nodes/conclude.py](../app/nodes/conclude.py) procesa la salida final aplicando dos guardarraíles clave:

1. **Mensaje Estructurado al Alcanzar el Límite de Iteraciones:**
   Si la ejecución se detuvo por el límite determinista de seguridad (`iteration >= max_iterations`, por defecto 3), sintetiza una respuesta informativa que:
   - Enumera las herramientas que se alcanzaron a consultar durante las iteraciones previas.
   - Explica con claridad que se detuvo por el guardarraíl de protección contra bucles infinitos.
   - Recomienda al usuario cómo formular una pregunta más acotada o específica para obtener directamente el dato faltante.

2. **Filtro Anti-Metacomentarios de Auditoría:**
   Mediante expresiones regulares compiladas, detecta si el modelo fundacional generó introducciones robóticas o de metacomentario (ej. *"La respuesta del tool get_weather indica..."*, *"El tool docker:ps devolvió..."* o *"cumpliendo con la solicitud"*). Al detectarlas, las despoja automáticamente y devuelve directamente la respuesta técnica limpia o el contenido directo entregado por la herramienta.

---

## 7. Navegación

- [← Anterior: 01. Arquitectura del Runtime](01_architecture.md)
- [Índice General](../README.md)
- [Siguiente: 03. Seguridad, Aislamiento de Red y Sandboxing →](03_security_sandboxing.md)
