# 07. Modos de Funcionamiento, Topologías de Despliegue y Registro

[← Volver al README](../README.md) | [01. Arquitectura](01_architecture.md) | [06. API REST](06_api_reference.md)

---

## 1. Visión y Desacoplamiento Arquitectónico

`jg_agente` ha sido concebido desde sus cimientos como un **Execution Plane autónomo, agnóstico y desacoplado**. No depende rígidamente de ninguna interfaz de usuario específica ni de un panel de administración concreto para ejecutar sus grafos cognitivos, coordinar herramientas o persistir estados en PostgreSQL.

Cualquier consumidor externo puede invocar al agente a través de su API REST privada utilizando el protocolo canónico de firmado **HMAC-SHA256**:
- **Bots de Mensajería:** Bots de Telegram, adaptadores de WhatsApp Business, Slack Apps o bots de Discord.
- **Orquestadores e Integradores:** Flujos en n8n, Apache Airflow, Temporal o Celery.
- **API Gateways & Backends:** Kong, Traefik, microservicios backend en Node.js, Go o Python.
- **Paneles de Control y Gobernanza:** Consolas administrativas como `jg_dashboard`.

---

## 2. ¿Para Qué Sirve Registrar los Agentes en un Dashboard?

Aunque `jg_agente` puede operar de forma completamente independiente, en despliegues corporativos, clústeres multi-agente y entornos productivos complejos existe la necesidad de **gobernanza, observabilidad y control humano**.

El registro de un agente en un panel de control proporciona:

1. **Inventario Dinámico y Catálogo de Capacidades:**
   Al registrarse, el agente publica automáticamente el resumen de su [`CapabilityRegistry`](../app/core/registry.py): herramientas activas, esquemas de parámetros esperados, modelos de inferencia y plugins instalados. Los operadores visualizan en tiempo real qué puede hacer cada agente sin inspeccionar código fuente ni archivos de despliegue.

2. **Gobernanza Human-In-The-Loop (HITL) Visual e Interactiva:**
   Cuando un agente formula un plan que incluye herramientas con nivel de riesgo `HIGH` o `CRITICAL` (por ejemplo, reiniciar un servicio, migrar una base de datos o ejecutar una transferencia de fondos), el grafo pausa la ejecución (`interrupt()`). El Dashboard ofrece una interfaz visual donde un operador humano puede auditar los parámetros, leer el razonamiento del LLM y **aprobar o rechazar la acción** con control de concurrencia pesimista (`lockForUpdate`).

3. **Monitorización de Salud y Heartbeats en Tiempo Real:**
   El agente emite periódicamente cada 30 segundos un pulso de telemetría hacia el endpoint de heartbeat (`/api/v1/agents/heartbeat`). Esto permite al Dashboard registrar latencias, memoria, estados operativos (`ACTIVE`, `DEGRADED`, `OFFLINE`) y alertar a los administradores ante fallos de conectividad.

4. **Aprovisionamiento Zero-Trust y Rotación Criptográfica:**
   En lugar de escribir contraseñas y secretos permanentes en variables de entorno o archivos estáticos, los administradores generan **Bootstrap Tokens temporales de un solo uso** (con caducidad de 24 horas). El agente utiliza este token para enrolarse de manera segura, negociar su `PERMANENT_AGENT_SECRET` y guardarlo de forma cifrada/restringida (permisos POSIX `0600`).

5. **Auditoría Forense Unificada y Trazabilidad:**
   Se centraliza la pista de auditoría: quién disparó la ejecución, qué usuario la autorizó, qué herramientas se ejecutaron en el sandbox y qué resultados se obtuvieron, correlacionando todo mediante `X-Correlation-ID`.

### La Solución de la Comunidad: `jg_dashboard`

Para cubrir todas estas necesidades de gobernanza sin obligar a cada organización a reinventar su propia interfaz de control, hemos desarrollado y puesto a disposición de la comunidad el proyecto de código abierto **`jg_dashboard`**.

- **Repositorio Oficial en GitLab:** [https://gitlab.com/javiergalvez-ia/jg_dashboard](https://gitlab.com/javiergalvez-ia/jg_dashboard)
- **Stack Técnico:** PHP 8.2+, Laravel 11, Filament v3, Livewire 3 y PostgreSQL independiente.
- **Licencia:** Doble licenciamiento (AGPL-3.0 código abierto para la comunidad / Comercial cerrada para despliegues corporativos).

---

## 3. Catálogo de Modos de Funcionamiento de `jg_agente`

`jg_agente` soporta cuatro modos de operación principales adaptados a diferentes niveles de infraestructura:

```mermaid
graph TD
    subgraph Modo 1: Standalone Directo
        T[Telegram / WhatsApp / API Gateway] -->|HTTP + HMAC| A1[jg_agente Independiente]
        A1 --> DB1[(PostgreSQL Checkpoints)]
    end

    subgraph Modo 2: Clúster Gestionado
        D[jg_dashboard] -->|Heartbeat / Bootstrap / HITL| A2[jg_agente Enrolado]
        U[Operador Humano] -->|Aprobación Web| D
        A2 --> DB2[(PostgreSQL Checkpoints)]
    end

    subgraph Modo 3: Local / Desconectado
        DEV[Desarrollador / CI/CD] -->|HTTP Local| A3[jg_agente Local]
        A3 --> MEM[(MemorySaver / Mock LLM)]
    end

    subgraph Modo 4: Edge / Worker Asíncrono
        Q[Cola de Tareas / Webhook Client] -->|POST /trigger?sync=false| A4[jg_agente Worker]
        A4 -.->|Callback HTTP Asíncrono| W[Endpoint Receptor Webhook]
    end
```

---

### Modo 1: Standalone / Desacoplado (Telegram, WhatsApp, API Gateways)

En este modo, el agente opera como un microservicio completamente independiente. No existe ninguna instancia de `jg_dashboard` en la red o, si existe, el agente no depende de ella.

- **Quién invoca:** Un backend de bots (Telegram Bot API, WhatsApp Cloud API adapter), un flujo de n8n o un API Gateway interno.
- **Autenticación:** El emisor conoce el `PERMANENT_AGENT_SECRET` y firma cada petición con `X-Signature`, `X-Timestamp` y `X-Agent-ID`.
- **Comportamiento ante Dashboard ausente:** Si `VERIFY_CREDENTIALS_ON_BOOT=true` y `DASHBOARD_URL` no responde, el agente emite un aviso en el log y **continúa arrancando normalmente sin bloquearse**.
- **Configuración recomendada (`.env`):**
  ```env
  AGENT_ID=agente_telegram_ventas
  PERMANENT_AGENT_SECRET=clave_secreta_compartida_de_32_bytes_minimo
  REQUIRE_DASHBOARD_REGISTRATION=false
  VERIFY_CREDENTIALS_ON_BOOT=false
  ENABLE_HEARTBEAT=false
  CHECKPOINT_SAVER=postgres
  DATABASE_URL=postgresql+asyncpg://postgres:pass@postgres:5432/agente_ventas
  ```

---

### Modo 2: Clúster Gestionado con Control Plane (`jg_dashboard`)

Diseñado para entornos empresariales con múltiples agentes especializados donde se requiere inventario centralizado, trazabilidad de accesos y aprobación humana (HITL).

- **Quién invoca:** `jg_dashboard` a través de su cliente interno `AgentHttpClient`.
- **Aprovisionamiento:**
  1. El administrador genera un **Bootstrap Token** en el panel de `jg_dashboard`.
  2. Se lanza el contenedor de `jg_agente` inyectando `AGENT_BOOTSTRAP_TOKEN`.
  3. Al arrancar, el agente invoca `POST /api/v1/agents/register` en el Dashboard, envía su catálogo de herramientas y recibe su credencial permanente.
  4. La credencial se guarda en el archivo local `.agent_credentials.json` con permisos restrictivos `0600`.
  5. El agente inicia su bucle de heartbeat en segundo plano cada 30 segundos.
- **Configuración recomendada (`.env`):**
  ```env
  DASHBOARD_URL=http://jg_dashboard:8080
  AGENT_BOOTSTRAP_TOKEN=boot_9a8f3b2c1d0e4a5b6c7d8e9f...
  REQUIRE_DASHBOARD_REGISTRATION=false   # Si es false, fallos transitorios de red no impiden el boot
  VERIFY_CREDENTIALS_ON_BOOT=true
  ENABLE_HEARTBEAT=true
  HEARTBEAT_INTERVAL_SECONDS=30
  ```

---

### Modo 3: Modo Desconectado / Local (Desarrollo y CI/CD)

Idóneo para desarrolladores que están programando nuevos plugins, ejecutando pruebas unitarias o levantando entornos de test en integración continua (CI) sin dependencias externas ni consumo de tokens en proveedores comerciales de IA.

- **Quién invoca:** Scripts de prueba, llamadas `curl` locales o tests automatizados con `pytest`.
- **Persistencia y LLM:** Utiliza `MemorySaver` en RAM para no requerir base de datos PostgreSQL, y proveedores de inferencia simulados (`LLM_PROVIDER=mock`).
- **Clasificador Heurístico de Intenciones en `MockChatModel` (`app/core/llm.py`):**
  El modelo simulado no es un simple generador estático de cadenas; implementa un evaluador determinista de intenciones:
  - **Filtro de Saludos vs Acción:** Cuando el grafo ejecuta la clasificación de intenciones, analiza el texto del usuario:
    - Palabras clave conversacionales (`hola`, `saludos`, `buenos días`, `quién eres`, `qué puedes hacer`).
    - Marcadores operacionales (`docker`, `servicio`, `reinicia`, `ejecuta`, `pod`, `cpu`, `memoria`, `disco`, etc.).
    - Si detecta marcadores operacionales, devuelve `ACTION`. Si solo contiene saludos o consultas de capacidades, clasifica como `GREETING`.
  - **Auto-generación de Tool Calls (`auto_tool_calls=True`):**
    Si se vinculan herramientas al modelo simulado, `MockChatModel` busca coincidencias léxicas entre el texto del usuario y los nombres de las herramientas registradas en `CapabilityRegistry`. Al encontrar coincidencia, sintetiza automáticamente una llamada `tool_call` con identificador único y argumentos simulados (`{"query": prompt}`), permitiendo probar todo el ciclo de ejecución y observabilidad de herramientas sin costes de API.
- **Configuración recomendada (`.env`):**
  ```env
  ENV=development
  AGENT_ID=jg_agente_local
  REQUIRE_DASHBOARD_REGISTRATION=false
  VERIFY_CREDENTIALS_ON_BOOT=false
  ENABLE_HEARTBEAT=false
  CHECKPOINT_SAVER=memory
  LLM_PROVIDER=mock
  ```

---

### Modo 4: Edge Worker / Ejecución Asíncrona con Webhooks

Orientado a operaciones de larga duración (análisis de grandes volúmenes de datos, despliegues de infraestructura o compilación de informes).

- **Quién invoca:** Sistemas de colas (RabbitMQ, SQS, Redis) o servicios HTTP asíncronos.
- **Flujo de Trabajo:**
  1. El cliente invoca `POST /executions/trigger?sync=false` pasando el parámetro `callback_url` dentro del esquema `AgentInput`.
  2. `jg_agente` valida la firma HMAC, encola la tarea en background mediante `asyncio.create_task` y responde de inmediato con `202 Accepted` y el `execution_id`.
  3. El grafo ejecuta todos sus pasos cognitivos y herramientas.
  4. Al concluir (o fallar), el servicio emite una notificación HTTP `POST` hacia la `callback_url` con el resultado final estructurado (`AgentOutput`), aplicando reintentos exponenciales configurables (`EXECUTION_CALLBACK_MAX_RETRIES=3`).

---

## 4. Resiliencia de Inferencia LLM: Backoff Adaptativo ante HTTP 429

Para proveedores compatibles con OpenAI (`OpenAICompatibleChatModel` en `app/core/llm.py`), el runtime incorpora gestión activa de saturación y cuotas de inferencia (*Rate Limiting*):

```text
┌────────────────────────────────────────────────────────┐
│             Llamada de Inferencia al Proveedor LLM     │
└──────────────────────────┬─────────────────────────────┘
                           │
                 ¿Respuesta HTTP 429?
                 ├── NO ──► Procesa choices y tool_calls
                 │
                 └── SÍ (Hasta 3 reintentos)
                      │
                      ▼
         Inspección Inteligente de Cabeceras
         ├── ¿Cabecera 'retry-after'? ──► Pausa = max(float(val), 1.0s)
         │
         ├── ¿Cabecera 'x-ratelimit-reset-tokens'?
         │   ├── Formato con sufijo 'ms' ──► Pausa = val / 1000s
         │   └── Formato con sufijo 's'  ──► Pausa = val en segundos
         │
         └── Ninguna presente ──► Backoff lineal: 2.5s * (intento + 1)
                      │
                      ▼
         await asyncio.sleep(wait_seconds) (No bloqueante)
                      │
                      ▼
         Reintento transparente de la petición
```

- **Soporte de Unidades Múltiples:** Parsea automáticamente cabeceras emitidas por proveedores de alta velocidad (Groq, Together AI, Cerebras, vLLM) en milisegundos (`ms`) o segundos (`s`).
- **Suspensión No Bloqueante:** Utiliza `asyncio.sleep()`, permitiendo que el Event Loop de FastAPI continúe gestionando peticiones concurrentes, heartbeats y endpoints de telemetría mientras espera a que se restablezca la cuota del proveedor.

---

## 5. Matriz Comparativa de Modos

| Característica | Modo 1: Standalone | Modo 2: Gestionado (`jg_dashboard`) | Modo 3: Desconectado / Local | Modo 4: Asíncrono / Webhook |
| :--- | :--- | :--- | :--- | :--- |
| **Dependencia de Dashboard** | Nula | Opcional / Recomendada | Nula | Nula o Gestionada |
| **Invocadores típicos** | Telegram, WhatsApp, n8n | Consola Web, Operadores HITL | Desarrollador, Pytest | Colas de tareas, Cron jobs |
| **Resolución de Secreto** | Variable de entorno fija | Bootstrap Token $\rightarrow$ `.agent_credentials.json` | Clave dummy en memoria | Variable de entorno o Token |
| **Gobernanza HITL** | Vía API REST (`/approve`) | Interfaz Web Interactiva (Filament) | Auto-aprobación o mock | Webhook de solicitud |
| **Heartbeat activo** | Desactivado (`false`) | Activo cada 30 segundos | Desactivado | Opcional |
| **Backend Checkpointer** | PostgreSQL (`DualPostgresSaver`) | PostgreSQL (`DualPostgresSaver`) | Memoria (`MemorySaver`) | PostgreSQL |
| **Tolerancia a fallos de red** | 100% aislable (Air-gapped) | Modo degradado si dashboard cae | 100% autónomo | Reintentos con backoff |

---

## 6. Navegación y Referencias Relativas

- [01. Arquitectura del Runtime](01_architecture.md) — Topología y componentes fundamentales.
- [02. Grafo Cognitivo y Máquina de Estados](02_cognitive_graph.md) — Ciclo reflexivo de 10 nodos.
- [03. Seguridad, Aislamiento de Red y Sandboxing](03_security_sandboxing.md) — Guardarraíles y SSRF.
- [04. Persistencia, Estado y Checkpointing](04_persistence_state.md) — PostgreSQL y resiliencia transaccional.
- [05. Ciclo de Vida y Ecosistema de Plugins](05_plugin_lifecycle.md) — Autodescubrimiento y empaquetado.
- [06. Referencia de API REST Privada](06_api_reference.md) — Catálogo de endpoints y parámetros.
- [Volver al README Principal de `jg_agente`](../README.md)
