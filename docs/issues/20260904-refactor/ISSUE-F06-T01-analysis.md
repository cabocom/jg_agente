# Análisis Técnico — ISSUE-F06-T01

## 1. Identificación y Metadatos
- **Issue ID:** `ISSUE-F06-T01`
- **Título:** Implementación de nodo opcional: observe
- **Fase:** FASE 06 (Nodos Opcionales y Motores Cognitivos)
- **Prioridad:** High
- **Complejidad Estimada:** M
- **Dependencias:** `ISSUE-F05-T01`
- **Criterios de Aceptación:**
  - Nodo `observe` invoca el `ObserverEngine` registrado y almacena el diccionario de snapshot en el estado sin acoplarse al dominio.

---

## 2. Contexto y Objetivos Técnicos
En la arquitectura del Execution Plane de `jg_agente`, el grafo LangGraph cuenta con nodos troncales obligatorios (`reason`, `execute`, `conclude`) y nodos opcionales que se activan condicionalmente según las capacidades expuestas por los plugins cargados en `CapabilityRegistry`.

El nodo `observe`:
1. Se sitúa entre el punto de entrada `START` y el nodo `reason` (`START -> observe -> reason`).
2. Si existe un `ObserverEngine` registrado, se ejecuta para recopilar telemetría previa y snapshot del entorno (por ejemplo, estado de servicios, conectividad, métricas).
3. Debe ser **completamente agnóstico del dominio**: el Core no debe referenciar Docker, Kubernetes, bases de datos o servicios cloud específicos.
4. Debe admitir ejecución polimórfica: invocación de `observe()`, `discover()` o `collect()`, de forma asíncrona (`async def`) o síncrona (`def`), pasando el estado actual o sin argumentos.
5. Registra trazas de auditoría estructuradas (`event_type="observe_completed"`) con métricas de tiempo (`duration_ms`).
6. Maneja fallos operacionales de forma contenida (`ExecutionError`), evitando que una excepción en la observación tire abajo la ejecución del agente.

---

## 3. Decisiones de Diseño y Arquitectura
- **Agnosticismo Radical:** `environment_snapshot` es un `dict[str, Any]` libre donde cada plugin vuelca la información relevante de su dominio.
- **Invocación Flexible y Polimórfica:** Se inspecciona la firma de los métodos candidatos (`observe`, `discover`, `collect`) con `inspect.signature` para determinar si aceptan el argumento `state`.
- **Tolerancia a Fallos:** Si el motor arroja una excepción, se atrapa con `logger.exception`, se registra un `ExecutionError(component="observe", fatal=False)` y se continúa con un snapshot vacío.
- **Delegación en GraphBuilder:** `default_observe_node` en `app/core/graph.py` delega directamente en `observe_node(state, registry=registry)`.

---

## 4. Plan de Pruebas
1. Invocación asíncrona con motor mock (`AsyncMockObserver`).
2. Invocación síncrona con motor mock (`SyncMockObserver`).
3. Comportamiento sin observer registrado (no-op seguro con evento skipped).
4. Inyección del contexto del estado (`state["request"]`).
5. Soporte de nombres de métodos alternativos (`discover()`).
6. Contención segura de excepciones del motor (`FailingObserver`).
7. Integración end-to-end dentro de un grafo LangGraph compilado con `GraphBuilder`.
