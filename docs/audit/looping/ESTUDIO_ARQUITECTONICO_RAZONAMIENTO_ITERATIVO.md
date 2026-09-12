# Estudio arquitectónico independiente: razonamiento iterativo

**Ámbito auditado:** `jg_agente` y el consumidor de trazas en `jg_dashboard`.

**Método:** lectura del código ejecutable, contratos y pruebas. La documentación histórica sólo se usó como índice, no como evidencia. No se modificó código de producto. El árbol de trabajo ya contenía cambios locales en `jg_agente` y Dashboard; no forman parte de este estudio.

## 1. Resumen ejecutivo

El grafo real es lineal. No hay retorno desde `verify` ni una semántica de “seguir”: `verify` sólo enruta a `rollback` (si falla y hay compensación disponible) o a `conclude`. Por tanto el sistema **no soporta todavía tareas iterativas** dentro de una ejecución.

La opción recomendable es **C, ciclo flexible**, con una precisión importante: no crear un nodo genérico adicional sólo para nombrar la decisión. El `VerifierEngine` debe emitir una evaluación estructurada del objetivo y una recomendación de continuación; `route_after_verify` debe ser el único router que la interprete. Las rutas han de ser `conclude`, `reason`, `observe`, `rollback` y, cuando falte información humana, una terminación explícita como `conclude` con estado/razón `needs_user_input` (o un futuro interrupt dedicado si se decide implementar una conversación suspendida).

La separación correcta es:

```
ObserverEngine = refresco amplio, estandarizado y proactivo del entorno
AgentTool      = consulta o acción puntual, elegida por el LLM/plan
VerifierEngine = prueba del efecto y del cumplimiento del objetivo
```

Una tool de lectura ya es válida y debe poder alimentar `reason → execute(read) → reason`; eso no sustituye el refresco de un `ObserverEngine`, que puede ser necesario tras una mutación. La clave es conservar ambos, no tratarlos como equivalentes.

## 2. Cómo funciona realmente el grafo actual

`GraphBuilder.build()` arma una topología estática al arrancar según las capacidades registradas. Sus nodos obligatorios son `reason`, `execute` y `conclude`; `observe`, `plan`, `risk_assess`, `human_approval`, `verify` y `rollback` son opcionales ([`app/core/graph.py`](../../../app/core/graph.py)). La topología completa efectiva es:

```
START → observe? → reason → plan? → risk_assess? → human_approval? → execute
                                                              ↓
                                               verify? → rollback? → conclude → END
```

Los detalles relevantes, que corrigen el diagrama conceptual del encargo, son:

- `reason` puede saltar directamente a `conclude`, `plan`, `risk_assess` o `execute`.
- `plan` siempre pasa por `risk_assess` cuando éste existe.
- `execute` siempre llega a `verify` cuando hay `VerifierEngine`; sin verificador termina directamente.
- `route_after_verify()` sólo detecta `FAIL`/`DEGRADED` para optar por `rollback`; en todo otro caso concluye. Ignora cualquier `resolved` que el verificador produzca.
- Se compila un `MemorySaver` por defecto si no se inyecta otro saver. La API normalmente inyecta el factory configurado, que intenta `PostgresSaver` y degrada a memoria.

No se encontró `recursion_limit`, `max_iterations`, contador de iteraciones, ni arista de vuelta en Core, plugins o tests.

## 3. Qué hacen realmente observe/reason/plan/execute/verify/conclude

| Elemento | Comportamiento real | Limitación relevante para un loop |
|---|---|---|
| `observe` | Resuelve el único observer registrado y llama, por convención flexible, a `observe`, `discover` o `collect`. Sobrescribe `environment_snapshot`; añade auditoría y un `CognitiveStepRecord`. | No mantiene historial/versiones de snapshots ni los entrega automáticamente al LLM. Puede ejecutarse de nuevo, pero el grafo no tiene ruta para hacerlo. |
| `reason` | Envía al LLM el prompt original (`request.prompt`) y `messages`; vincula todas las tools. Devuelve un `AIMessage` y un `IntentModel`: `act`, `plan` o `conclude`. | No consume explícitamente `environment_snapshot`, `execution_records` ni `verification_results`; sólo ve resultados que estén en `messages`. |
| `plan` | Delega en `create_plan`/`plan`/`build_plan`/`generate_plan`; crea un `ExecutionPlan` con pasos y riesgo. Si falla, usa un fallback que puede escoger la primera tool registrada. | Sobrescribe un único `plan`; no hay versión, relación con una iteración ni invalidación de pasos ya ejecutados. |
| `execute` | Ejecuta en serie los pasos del plan o los `tool_calls` del intent, bajo `SecurityGuard`; registra `StepExecutionRecord`. Sólo crea `ToolMessage` para tool calls directas del LLM, no para pasos originados en plan. | Es tanto lector como actuador. Los resultados de pasos planificados no llegan al LLM como mensajes; no hay deduplicación/idempotency key por intento. |
| `verify` | Ejecuta el verificador de plugin o un fallback que sólo mira fallos en records/errores. Añade una entrada de `verification_results`. | No decide/representa formalmente continuación, pregunta al usuario o estado de objetivo. |
| `conclude` | Convierte fallo de step, error fatal o `FAIL`/`DEGRADED` de verificación en fracaso; de otro modo marca `is_resolved=True`. Sintetiza el `AgentOutput`. | Confunde «no hubo fallo» con «objetivo satisfecho». No puede cerrar una ejecución parcial con semántica de información insuficiente. |

## 4. ObserverEngine vs AgentTool

### `observe` es una observación real, no sólo inicialización

El único observer de producción, `InfraDiscoveryEngine.observe()`, consulta host, Docker y Kubernetes en cada llamada, detecta incidentes y devuelve una fotografía JSON serializable ([`plugins/jg_plugin_devops/discovery.py`](../../../plugins/jg_plugin_devops/discovery.py)). Sus métricas, contenedores e incidentes pueden cambiar después de una mutación; por tanto conceptualmente debe poder ejecutarse por iteración. El Core acepta observadores síncronos/asíncronos y las firmas con o sin `state`, de modo que otros plugins pueden tener el mismo comportamiento.

Actualmente existe un solo `ObserverEngine` singleton y su resultado reemplaza `state["environment_snapshot"]`. No hay observadores en el plugin conversacional.

### Las tools ya incluyen consultas de sólo lectura

`AgentTool` declara `tool_type` (`OBSERVER`, `ACTUATOR`, `VERIFIER`, `READ`, `MUTATION`) y `read_only`; `ToolResult.output` acepta cualquier dato y sus `metadata` y `rollback_context` se preservan ([`app/models/tools.py`](../../../app/models/tools.py)). `get_weather` y `get_news` son tools `READ`, `read_only=True`; las tools Docker combinan capacidades de lectura y mutación. `execute` no restringe herramientas por tipo: puede ejecutar ambas. Por tanto no es un nodo reservado a mutaciones.

Para un tool call directo, `execute` incorpora un `ToolMessage` con output/error a `messages`, y la siguiente invocación de `reason` lo vería. Eso permite **por contrato de datos**, aunque no por topología actual, el patrón `reason → tool(read) → reason`. Para pasos de un plan no se inserta `ToolMessage`; en un loop, ese hueco impediría que el LLM razone sobre el resultado salvo que consulte estructuras de estado que hoy no se serializan en su prompt.

### Separación propuesta

Hay solapamiento funcional: ambas hacen I/O de observación. La distinción debe mantenerse y documentarse por alcance e iniciativa, no por una imposibilidad técnica:

- Un `ObserverEngine` recopila una vista transversal, repetible y de contrato plugin-específico. Debe ser apropiado para refrescar contexto global tras cambios o cuando la verificación indique que el estado observado quedó obsoleto.
- Una `AgentTool` es una capacidad direccionable con argumentos; sirve para una pregunta/accción concreta, incluida una consulta read-only barata y selectiva.

No conviene convertir el observer en una tool ni prohibir tools de lectura. Sí conviene evitar que plugins escondan una observación global cara dentro de una tool que el LLM pueda repetir sin presupuesto.

## 5. Problema arquitectónico detectado

El fallo no es sólo la arista ausente. El sistema usa `PASS` como si significase «objetivo del usuario resuelto». El `DevopsVerifierEngine` declara `resolved=True` tras comprobar records/errores y después afirma salud de servicio, pero no consulta activamente dicho servicio ([`plugins/jg_plugin_devops/verifier.py`](../../../plugins/jg_plugin_devops/verifier.py)). El router ni siquiera lee `resolved`. Así que hoy no existe una separación fiable entre:

```
tool ejecutada correctamente  !=  estado post-acción aceptable  !=  objetivo del usuario satisfecho
```

`ToolResult.success` responde a la primera; un verifier de dominio debe responder al menos a las otras dos. Esta carencia debe resolverse antes de habilitar un ciclo; de otro modo el loop sólo repetirá por fallos técnicos o terminará falsos positivos.

## 6. Comparación de alternativas

| Alternativa | Encaje real | Ventaja | Coste/riesgo | Veredicto |
|---|---|---|---|---|
| A. `verify → reason` | Encaja con `messages`, tool calling y la necesidad de replantear. | Simple; habilita leer con tools y replanificar. | No refresca el snapshot tras mutaciones; puede decidir sobre telemetría obsoleta. | Insuficiente como arquitectura única. |
| B. `verify → observe` | El observer es realmente una consulta actual del entorno. | Excelente para confirmar efectos físicos del sistema. | Fuerza recogidas globales incluso cuando basta un dato puntual o sólo hay que replanificar; penaliza plugins sin observer. | Insuficiente como arquitectura única. |
| C. Router flexible desde `verify` | Respeta engines opcionales, tools heterogéneas y la topología dinámica existente. | Cada plugin puede expresar si necesita refresco, nuevo razonamiento, usuario, rollback o cierre. | Exige un contrato de resultado explícito y límites fuertes. | **Recomendada.** |
| D. Bucle fijo `verify → observe → reason` | Posible con el grafo actual. | Predecible y fácil de dibujar. | Observación innecesaria, coste y latencia altos; no sirve en grafos sin observer; complejidad accidental. | No recomendada. |

El impacto de C es acotado: una arista condicional adicional y enriquecimiento de estado/contratos; no un nuevo grafo ni una ejecución nueva. HITL, saver y Dashboard ya son compatibles a nivel estructural, aunque requieren registros de iteración e idempotencia explícitos.

## 7. Arquitectura recomendada

Mantener una sola instancia de `StateGraph` y una sola `AgentInput`. Tras cada `verify`, el resultado normalizado debe contener un campo equivalente a este pseudocontrato:

```
goal_status: resolved | not_resolved | unknown | needs_user_input
next_action: conclude | reason | observe | rollback | request_input
reason: texto
evidence: datos estructurados
```

`next_action` es una recomendación del verificador, no una orden sin control. El router debe validar que el destino está presente en la topología, que el presupuesto permite continuar y que no hay condición de seguridad/rollback prioritaria. Si no existe observer y se solicita `observe`, debe caer de forma explícita a `reason` con una observación diagnóstica, no fallar ni inventar una ruta.

No crear un nodo «decisión» independiente: hoy el único consumidor natural de la evaluación posterior es `route_after_verify`; introducirlo añadiría un checkpoint y trazas sin aportar una responsabilidad nueva. La evaluación pertenece al verificador; el enrutado determinista, al router.

## 8. Cómo debería ser el ciclo

```
START → observe? → reason → plan? → risk → approval? → execute → verify
                                                               │
            ┌──────────── resolved ───────────────────────────┴→ conclude → END
            ├──────────── need targeted tool / replan ────────→ reason
            ├──────────── refresh global state ───────────────→ observe? → reason
            ├──────────── compensation required ──────────────→ rollback → conclude
            └──────────── user information required ──────────→ conclude(needs_user_input)
```

Cada regreso a `reason` debe recibir el objetivo original y el contexto material de las iteraciones previas. `plan` debe producir un plan de la iteración actual, no reutilizar sin más los pasos ya completados. El `risk_assess` debe repetirse para cada nuevo conjunto de pasos; una aprobación previa no autoriza herramientas o argumentos nuevos.

## 9. Cambios necesarios en AgentState

Conservar `request` como fuente canónica e inmutable de `AgentInput`; por tanto el prompt original debe estar disponible siempre. `messages`, `execution_records`, `cognitive_steps`, `verification_results`, `errors` y `audit_trail` ya tienen reducers de append; deben conservarse. `environment_snapshot` y `plan` se sobrescriben hoy y necesitan historia o referencia de versión.

Cambios mínimos recomendados:

- `iteration: int` y `iteration_started_at`; `max_iterations`, `max_tool_calls`, `max_elapsed_ms` y presupuesto LLM como límites de ejecución inmutables/iniciales.
- `objective`: copia normalizada del objetivo original y `goal_status`; no derivar el objetivo sólo del último `IntentModel`.
- `observation_history` con `{iteration, snapshot_id, captured_at, snapshot/summary}` y mantener `environment_snapshot` como la última vista por compatibilidad.
- `plan_history` o `plan_iteration`; conservar `plan` actual pero etiquetar steps y records con `iteration` y un `attempt_id` estable.
- `verification_results` con `goal_status`, `next_action`, evidencia y `iteration`; no sólo `status` técnico.
- `tool_calls_count` y `continuation_reason`; registrar los topes, la decisión de router y el estado de salida.

No guardar objetos de plugin/LLM en estado. Todos los campos nuevos deben ser JSON-serializables o estar añadidos al serializer permitido de checkpoints. Si se incorporan modelos Pydantic nuevos, actualizar la allowlist de `app/core/checkpointer.py`.

## 10. Cambios necesarios en LangGraph

- Hacer que `route_after_verify` priorice rollback según política, después límites, y finalmente `goal_status`/`next_action`.
- Añadir a su `path_map` sólo rutas existentes: `observe` únicamente si la topología lo tiene; `reason` siempre; `conclude` siempre; `rollback` si existe.
- Incrementar la iteración al elegir una continuación, una vez por ciclo, no en cada nodo.
- Hacer que `reason` reciba una representación acotada de snapshot, últimos resultados de tools y verificación; y que `execute` publique `ToolMessage` también para resultados de plan cuando vaya a volver a `reason`.
- No cambiar el grafo por cada iteración ni recrear `AgentInput`; la API debe seguir usando el mismo `thread_id` y `execution_id`.
- Configurar `recursion_limit` de LangGraph además de límites de negocio, como última barrera. Una excepción por límite debe traducirse en salida controlada/auditable, no sólo en error genérico.

## 11. Impacto en HITL

La base es apta: `human_approval_node` usa `interrupt()` y el checkpointer; la API reanuda con `Command(resume=...)` y el mismo `thread_id`. Las pruebas cubren pausa/reanudación. Un loop no rompe ese mecanismo si el checkpoint incluye el contador, el plan/attempt vigente y la acumulación de trazas.

Hay dos requisitos obligatorios:

- Recalcular riesgo en cada nueva iteración antes de ejecutar; no reutilizar `approval` como bypass para un plan diferente. La aprobación debe vincularse a `plan_id`/hash de pasos y caducar al cambiar argumentos o alcance.
- Hacer las tools mutantes idempotentes por `execution_id + iteration + step_id/attempt_id`, o detectar que ya se aplicaron al reanudar. `AgentTool.idempotent` es sólo metadato hoy; `execute_node` no usa una clave de idempotencia.

## 12. Impacto en rollback

El modelo actual permite rollback automático únicamente al fallar `verify`, para todos los records completados con `rollback_context`, en orden inverso, y finaliza como `FAILED`. No soporta que el agente siga razonando tras una verificación fallida ni que elija selectivamente revertir una acción de una iteración anterior.

No hace falta un sistema de compensación nuevo. Mantener `AgentTool.rollback()` como responsabilidad de cada tool es correcto. Sí hace falta que la política superior distinga:

- fallo irrecuperable/seguridad: rollback prioritario y finalizar;
- objetivo no resuelto pero entorno seguro: continuar sin rollback;
- compensación razonada de una acción anterior: sólo si una futura política lo permite y con selección explícita por `attempt_id`, no con el actual «revertir todo lo reversible».

Hasta que exista esa selección, no enrutar `FAIL` automáticamente a `reason` tras mutaciones reversibles: preserva la conducta conservadora actual.

## 13. Impacto en checkpointing

LangGraph guarda checkpoints por `thread_id`; `DualPostgresSaver`/`MemorySaver` ya pueden almacenar estados entre nodos. Por ello varios ciclos y un interrupt intermedio son posibles en principio dentro del mismo grafo. No se ha encontrado prueba de múltiples iteraciones porque no existen las aristas.

Cambios necesarios: serializar los nuevos tipos, incluir versión/iteración/attempt en cada snapshot y probar recuperación desde un checkpoint entre iteraciones y después de un interrupt. El fallback silencioso de Postgres a memoria es un riesgo operativo: una ejecución larga/HITL no debe prometer recuperación entre procesos si está usando `MemorySaver`; Dashboard/API deben exponerlo como persistencia degradada.

## 14. Impacto en Dashboard/tracing

El Core ya produce `cognitive_steps` append-only y `execution_records`; `conclude` los expone en `AgentOutput.data`. El endpoint de detalle recupera ambos del checkpoint y prioriza la traza cognitiva. El Dashboard ya renderiza el array completo y conserva el orden, por lo que puede mostrar nodos repetidos sin cambiar su modelo fundamental.

Actualmente no hay `iteration` en `CognitiveStepRecord` ni en `StepExecutionRecord`; una secuencia repetida se verá pero será ambigua. Añadir `iteration`, `attempt_id` y `phase`/`continuation_reason` a `details` (o como campos tipados) permite agruparla visualmente:

```
Iteración 1: observe → reason → plan → execute → verify (not_resolved)
Iteración 2: reason → plan → execute → verify (resolved) → conclude
```

No crear una nueva ejecución de Dashboard por ciclo. Persistir el resultado final como hoy es suficiente para una primera entrega, pero si se requiere visualización en vivo se deberán publicar/guardar snapshots intermedios; la BD `core_executions` actual se actualiza principalmente al inicio, pausa HITL y final.

## 15. Límites y protección contra loops infinitos

El control debe vivir en Core/router, no en cada plugin ni en el LLM. Propuesta inicial configurable por ejecución/política: máximo de iteraciones, máximo de tool invocations, deadline total, presupuesto de tokens/coste y límite de la recursión del grafo. Incrementar y verificar antes de tomar un arco de continuación.

Además, detectar progreso nulo con una huella de `{goal, next_action, tool_name, args normalizados, snapshot/version}` repetida. No debe bloquear lecturas legítimamente repetidas, pero sí requerir una razón/evidencia nueva para repetir la misma operación. Al alcanzar un límite: no ejecutar más tools, registrar `stop_reason=iteration_limit|tool_budget|deadline|no_progress`, producir una salida no-resuelta clara y conservar toda la evidencia.

## 16. Riesgos y edge cases

- Un LLM puede pedir la misma mutación después de un timeout ambiguo; sólo una clave de idempotencia o una comprobación posterior evita doble efecto.
- El resultado de una tool planificada hoy no entra en `messages`; sin corregirlo, el siguiente `reason` puede alucinar que no tiene evidencia.
- Un snapshot completo puede ser grande o sensible; pasar al LLM sólo un resumen/slices autorizados y mantener el bruto en estado/auditoría con políticas de redacción.
- Repetir `observe` puede detectar cambios exógenos; eso es deseable, pero exige timestamp/version para no comparar fotografías incomparables.
- Un verificador que responda `unknown` no debe convertirse ni en `PASS` ni en loop ilimitado.
- Los grafos sin `VerifierEngine` no tienen evidencia suficiente para continuar con seguridad: conservar `execute → conclude` hasta que un plugin aporte una semántica de objetivo.
- Un plugin puede no tener observer. La ruta flexible debe degradar de forma explícita, no obligar a un `NoOp` que parezca observación real.

## 17. Plan de implementación por pasos para otra IA

1. Acordar y tipar el contrato de resultado de verificación/objetivo, incluyendo los destinos permitidos y la semántica de `unknown` y `needs_user_input`.
2. Extender `AgentState`, records y serializer con iteración, historial/versionado y presupuestos; conservar compatibilidad con los campos actuales.
3. Hacer que `reason` reciba contexto estructurado y acotado; hacer que `execute` convierta resultados relevantes de plan en mensajes/evidencia para la siguiente razón.
4. Actualizar `VerifierEngine` DevOps para basar `resolved` en checks reales del dominio, no sólo en records, y emitir la recomendación de continuación.
5. Implementar el router posterior a verify y aristas condicionales, con validación de capacidades y límites. No añadir nodo decisor.
6. Integrar idempotency/attempt identity en ejecución y vincular HITL a plan/alcance; repetir riesgo por iteración.
7. Preservar rollback conservador; añadir selección de compensación sólo si un caso de uso concreto lo exige.
8. Propagar iteration/attempt a API y Dashboard; agrupar la traza sin perder la lista lineal existente.
9. Activar configuración operativa de límites y telemetría de coste/duración; documentar degradación de persistencia.

## 18. Tests que deberían existir

- `verify → reason` con tool read-only: el segundo LLM recibe exactamente el `ToolMessage` y conserva el prompt inicial.
- `verify → observe → reason`: una tool muta un fake environment, el segundo snapshot es distinto y está etiquetado con iteración.
- Objetivo resuelto: no se ejecuta una segunda iteración; `is_resolved` proviene de `goal_status`, no sólo de `ToolResult.success`.
- `unknown` y ausencia de observer: degradación determinista a `reason` o salida de información insuficiente, según contrato.
- Presupuesto: iteraciones, tools, deadline, recursion limit y progreso nulo producen salida controlada y auditada.
- HITL en iteración 2: pausa, restaura desde saver, aprueba, no reejecuta la tool de iteración 1 y vuelve a verificar.
- Cambio de plan tras aprobación: exige nueva aprobación; una aprobación vieja no hace bypass.
- Rollback: fallo crítico reversible concluye tras compensar; fallo no resolutivo seguro continúa sin rollback; ninguna compensación duplicada tras resume.
- Checkpoint Postgres: múltiples checkpoints, recuperación de proceso, serialización de los nuevos campos y endpoint de detalle correcto.
- Dashboard/API: secuencia repetida se ordena y agrupa por iteración; conserva ejecuciones antiguas sin `iteration`.
- Regresión de topologías mínimas: plugins conversacionales sin observer/planner/verifier siguen teniendo `reason → execute → conclude`.

## 19. Qué NO debería modificarse

- No crear un grafo ni una `AgentInput`/ejecución nuevos por iteración.
- No introducir ramas por dominio (`if devops`, `if conversational`) en Core.
- No eliminar `ObserverEngine` ni las `AgentTool` de lectura; resolver su solapamiento por contrato.
- No convertir todas las observaciones en mensajes LLM sin filtro ni pasar snapshots brutos indiscriminadamente.
- No tratar `ToolResult.success` como resolución del objetivo.
- No eliminar el checkpoint/HITL nativo ni aprobar automáticamente un plan nuevo con autorización vieja.
- No reemplazar rollback de tools por un orquestador de compensación complejo antes de disponer de un caso que requiera selección granular.

## Evidencia y validación realizada

Se inspeccionaron `app/core/graph.py`, `app/models/state.py`, `app/models/tools.py`, `app/plugins/base.py`, todos los nodos auditados, los engines y tools de ambos plugins, checkpointing, API de ejecuciones y el consumidor Dashboard. Se ejecutó:

```
.venv/bin/pytest -q tests/test_graph_builder.py tests/test_node_observe.py \
  tests/test_node_plan.py tests/test_nodes_verify_rollback.py \
  tests/test_node_human_approval.py tests/test_checkpointer.py
```

Resultado: **41 passed, 2 skipped**. Los dos skips requieren el contenedor PostgreSQL `jg_agente_postgres` local en `localhost:5433`; no son fallos de las pruebas.
