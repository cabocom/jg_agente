# jg_agente

**Enterprise Cognitive Agent Runtime for Private & Secure Environments**  
*Motor Autónomo de Ejecución Cognitiva, Gobernanza HITL y Reversibilidad Transaccional*

---

## 1. Visión General: ¿Qué es `jg_agente`?

`jg_agente` es un **runtime industrial de agentes de Inteligencia Artificial Cognitiva** diseñado para ejecutarse de forma segura y aislada en **redes privadas, infraestructuras on-premise, nubes soberanas o entornos de alta conformidad (air-gapped)**.

Construido sobre una arquitectura basada en grafos de estados ([LangGraph](https://github.com/langchain-ai/langgraph)) y microservicios asíncronos de alto rendimiento ([FastAPI](https://fastapi.tiangolo.com/)), `jg_agente` proporciona un motor de ejecución estrictamente agnóstico que desacopla la capacidad de razonamiento e inferencia de las herramientas de dominio.

A diferencia de los frameworks tradicionales de automatización o chatbots convencionales, `jg_agente` implementa **gobernanza humana obligatoria (Human-In-The-Loop)**, **evaluación preventiva de riesgos**, **mecanismos automáticos de compensación y rollback**, y un estricto modelo de **seguridad Zero-Trust**.

---

## 2. Pilares de Valor y Ventajas Competitivas

### 🔒 Ejecución Soberana en Redes Privadas (Air-Gapped Ready)
- Opera como un plano de ejecución (*Execution Plane*) ciego a Internet pública, consumiendo estímulos normalizados (`AgentInput`) y devolviendo respuestas estructuradas auditadas (`AgentOutput`).
- Comunicación entre el Plano de Control y el Runtime blindada mediante **firmas criptográficas canónicas HMAC-SHA256** con protección anti-replay (ventanas temporales y nonces únicos).

### 🛡️ Gobernanza Human-In-The-Loop (HITL) Nativa
- Toda acción identificada con nivel de riesgo crítico o mutaciones de infraestructura (`RiskLevel >= HIGH`) provoca la **pausa transparente y determinista del grafo cognitivo** mediante persistencia transaccional de checkpoints.
- Los operadores humanos pueden auditar la justificación técnica del plan, examinar los argumentos y autorizar o rechazar la mutación de forma remota antes de que se ejecute una sola línea de código en producción.

### 🔄 Reversibilidad Automática (Rollback Engine)
- Las herramientas mutantes declaran contratos formales de compensación (`rollback_func`).
- Si un paso del plan falla o un motor de verificación (`VerifierEngine`) detecta anomalías post-ejecución, el runtime activa el **bucle de reversión ordenada**, deshaciendo los cambios en orden cronológico inverso para garantizar la integridad del entorno.

### 🧩 Arquitectura Open-Core Agnóstica y Extensible
- El núcleo no contiene acoplamiento ni lógica de dominio preprogramada. Las herramientas, observadores y planificadores se descubren e inyectan dinámicamente mediante el ecosistema de plugins (`BasePlugin`) sobre contratos canónicos provistos por el SDK.
- Admite recarga de capacidades en caliente (*Hot-Reload*) y compilación dinámica de topologías cognitivas adaptadas a las capacidades detectadas en tiempo de arranque.

### 🧠 Orquestación de Modelos Polimórfica
- Compatible con modelos masivos de lenguaje de última generación tanto propietarios como de código abierto desplegados localmente (Groq, OpenAI, Gemini, Ollama, vLLM).

---

## 3. Arquitectura del Sistema

```text
┌────────────────────────────────────────────────────────────────────────┐
│                      CONTROL PLANE (jg_dashboard)                      │
│            Gobernanza · Inventario · HITL · Auditoría Operativa        │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Firmas HMAC-SHA256 (Red Privada)
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                      EXECUTION PLANE (jg_agente)                       │
│                                                                        │
│  ┌─────────────────────────┐            ┌───────────────────────────┐  │
│  │   FastAPI Private Core  │            │    CapabilityRegistry     │  │
│  │  /trigger  /health  HITL│            │ (Tools, Engines, Schemas) │  │
│  └────────────┬────────────┘            └─────────────▲─────────────┘  │
│               │ Invocación                            │ Registra      │
│               ▼                                       │ Capacidades   │
│  ┌─────────────────────────┐            ┌─────────────┴─────────────┐  │
│  │    LangGraph Engine     │            │      Plugins Ecosistema   │  │
│  │  (observe -> plan ->    │            │   (Empaquetados via SDK)  │  │
│  │   execute -> rollback)  │            └───────────────────────────┘  │
│  └────────────┬────────────┘                                           │
│               │                                                        │
│               ▼                                                        │
│  ┌─────────────────────────┐            ┌───────────────────────────┐  │
│  │      SecurityGuard      │◄──────────►│    Checkpointer Storage   │  │
│  │  (SSRF, Timeouts, HITL) │            │   (PostgreSQL Transacc.)  │  │
│  └─────────────────────────┘            └───────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Ciclo de Vida Cognitivo y Flujo de Decisión

El grafo de estados se compila dinámicamente durante el arranque del contenedor según los motores y herramientas registradas:

```text
                  [Entrada: AgentInput]
                            │
                            ▼
              ┌───────────────────────────┐
              │   1. Telemetría (observe) │ ──► (Opcional: ObserverEngine)
              └─────────────┬─────────────┘
                            ▼
              ┌───────────────────────────┐
              │  2. Inferencia (reason)   │ ──► (Inferencia LLM & Bindings)
              └─────────────┬─────────────┘
                            ▼
              ┌───────────────────────────┐
              │ 3. Formulación Plan (plan)│ ──► (Opcional: PlannerEngine)
              └─────────────┬─────────────┘
                            ▼
              ┌───────────────────────────┐
              │ 4. Evaluación de Riesgo   │
              │       (risk_assess)       │
              └─────────────┬─────────────┘
                            │
               ¿Riesgo >= HIGH o Mutación?
              ┌─────────────┴─────────────┐
        [SÍ]  ▼                           ▼  [NO]
    ┌───────────────────┐                 │
    │  Pausa en Checkpoint                │
    │  (human_approval) │                 │
    └─────────┬─────────┘                 │
              │ (Aprobación remota HMAC)  │
              └─────────────┬─────────────┘
                            ▼
              ┌───────────────────────────┐
              │  5. Ejecución Protegida   │ ──► (SecurityGuard + Sandbox + Timeouts)
              │         (execute)         │
              └─────────────┬─────────────┘
                            │
                            ▼
              ┌───────────────────────────┐
              │ 6. Verificación (verify)  │ ──► (Opcional: VerifierEngine)
              └─────────────┬─────────────┘
                            │
                     ¿Fallo detectado?
              ┌─────────────┴─────────────┐
        [SÍ]  ▼                           ▼  [NO]
    ┌───────────────────┐                 │
    │  Compensación     │                 │
    │    (rollback)     │                 │
    └─────────┬─────────┘                 │
              └─────────────┬─────────────┘
                            ▼
              ┌───────────────────────────┐
              │ 7. Consolidación (conclude│ ──► (Salida estructurada AgentOutput)
              └───────────────────────────┘
```

---

## 5. Configuración de Entorno (Variables de Docker Compose)

El runtime se parametriza mediante variables de entorno divididas estrictamente entre la infraestructura del núcleo y los requerimientos específicos de los plugins instalados.

### Bloque 1: Variables Mínimas del Núcleo (Core Runtime)

| Variable | Descripción | Valor por Defecto / Requisito |
|---|---|---|
| `ENV` | Entorno de ejecución (`development`, `production`). | `development` |
| `AGENT_ID` | Identificador único del agente en formato UUID o alfanumérico. | `jg_agente_local` |
| `AGENT_PORT` | Puerto interno en el que escucha el servidor ASGI Uvicorn. | `8000` |
| `UVICORN_WORKERS` | Número de workers concurrentes asíncronos. | `2` |
| `PERMANENT_AGENT_SECRET` | Secreto compartido de 64 caracteres para firma HMAC-SHA256 con el Dashboard. | **Requerido en producción** |
| `AGENT_BOOTSTRAP_TOKEN` | Token efímero de registro inicial (alternativo al pre-aprovisionamiento). | Opcional |
| `DASHBOARD_URL` | URL de red privada del Control Plane para telemetría y webhooks. | `http://jg_dashboard:8080` |
| `ENABLE_HEARTBEAT` | Habilita el emisor periódico de latidos y telemetría de salud. | `true` |
| `CREDENTIALS_FILE` | Ruta de persistencia segura de credenciales (permisos POSIX `0600`). | `/app/data/.agent_credentials.json` |
| `DATABASE_URL` | Cadena de conexión asyncpg a PostgreSQL para checkpoints y auditoría. | `postgresql+asyncpg://...` |
| `CHECKPOINT_SAVER` | Backend de persistencia de grafos (`postgres` o `memory`). | `postgres` |
| `LLM_PROVIDER` | Proveedor de inferencia LLM (`groq`, `openai`, `gemini`, `mock`). | `groq` |
| `LLM_MODEL` | Identificador del modelo fundacional a invocar. | `llama-3.3-70b-versatile` |
| `LLM_API_KEY` | Clave de acceso a la API del proveedor de LLM. | **Requerido** |
| `PLUGINS_DIR` | Directorio local donde se montan paquetes de plugins. | `plugins` |
| `ENABLED_PLUGINS` | Lista separada por comas de plugins que el agente debe activar. | Vacío (carga todos los descubiertos) |

### Bloque 2: Variables de Dominio y Plugins

Variables consumidas exclusivamente por plugins de especialidad si se encuentran instalados y activos:

| Variable | Plugin que la Requiere | Propósito y Uso |
|---|---|---|
| `DOCKER_HOST` | `jg_plugin_devops` | Socket o proxy TCP para monitorización de contenedores (`tcp://jg_docker_socket_proxy:2375`). |
| `AZURE_MAPS_KEY` | `jg_plugin_conversational` | Clave de Azure Maps para geolocalización y previsión meteorológica real en `WeatherTool`. |
| `TAVILY_API_KEY` | Plugins de Búsqueda Web | Clave de acceso al motor de búsqueda para herramientas de navegación en tiempo real. |

---

## 6. Despliegue Multi-Agente y Especialización

`jg_agente` utiliza una **única imagen universal de contenedor**. La especialización del agente no requiere reconstruir el software, sino que se define al arrancar mediante la composición de plugins y permisos:

```yaml
services:
  # Agente de Diálogo y Asistencia
  jg_agente_conversacional:
    image: registry.cabocom.net/javiergalvez-ia/jg_agente:latest
    environment:
      AGENT_ID: "a0000000-0000-0000-0000-000000000001"
      AGENT_NAME: "Agente Conversacional"
      ENABLED_PLUGINS: "jg_plugin_conversational"
      DATABASE_URL: "postgresql+asyncpg://postgres:${DB_PASS}@jg_agente_postgres:5432/jg_agente_conversacional"
      PERMANENT_AGENT_SECRET: "${JG_CONVERSATIONAL_SECRET}"
      AZURE_MAPS_KEY: "${AZURE_MAPS_KEY}"
    ports:
      - "127.0.0.1:8001:8000"

  # Agente SRE / DevOps de Infraestructura (con HITL)
  jg_agente_devops:
    image: registry.cabocom.net/javiergalvez-ia/jg_agente:latest
    environment:
      AGENT_ID: "a0000000-0000-0000-0000-000000000002"
      AGENT_NAME: "Agente DevOps"
      ENABLED_PLUGINS: "jg_plugin_devops"
      DATABASE_URL: "postgresql+asyncpg://postgres:${DB_PASS}@jg_agente_postgres:5432/jg_agente_devops"
      PERMANENT_AGENT_SECRET: "${JG_DEVOPS_SECRET}"
      DOCKER_HOST: "tcp://jg_docker_socket_proxy:2375"
    ports:
      - "127.0.0.1:8002:8000"
```

---

## 7. Madurez del Sistema y Resultados de Auditoría

El sistema ha sido sometido a rigurosas rondas consecutivas de auditorías técnicas y análisis exhaustivos de seguridad independiente (Septiembre 2026), alcanzando la máxima calificación de estabilidad.

### Veredicto Global: APTO PARA PRODUCCIÓN (LISTO)

- **Cobertura de Pruebas Automatizadas:** **312 tests automáticos** ejecutados en cada ciclo de integración continua (unitarios, estáticos y de integración de grafos).
- **Hitos de Endurecimiento Auditados:**
  1. **Blindaje Criptográfico HMAC-SHA256:** Canje seguro de credenciales con almacenamiento atómico POSIX `0600` (`os.replace` + `os.fsync`) y neutralización de ataques de repetición.
  2. **Defensa Profunda contra SSRF:** Validación determinista de destinos de red en herramientas (`SSRFValidator`), bloqueo estricto de RFC 1918, loopback, metadatos cloud y DNS pinning.
  3. **Aislamiento Multi-Agente en Persistencia:** Separación estricta de bases de datos por runtime (`jg_agente_conversacional` y `jg_agente_devops`) eliminando colisiones en el checkpointer LangGraph.
  4. **Protección Sandboxed con Timeouts Estrictos:** Invocación de herramientas protegida con límites temporales duros (`tool.timeout_sec`) y cancelación cooperativa `asyncio.wait_for`.
  5. **Concurrencia Pesimista en el Control Plane:** Transaccionalidad atómica y bloqueos pesimistas para impedir dobles aprobaciones en operaciones de riesgo humano (HITL).

---

## 8. Verificación de Calidad

Para ejecutar la suite de calidad localmente (linters, comprobación de tipos estricta y tests unitarios):

```bash
# Verificación integral automatizada
./scripts/check.sh

# Ejecución directa con pytest
pytest tests/
```

---

## 9. Política y Matriz de Licenciamiento

`jg_agente` forma parte del ecosistema de inteligencia artificial **jg_ia**, cuya distribución se articula bajo un modelo claro que equilibra la extensibilidad abierta con la protección de la propiedad intelectual industrial.

### Matriz de Licenciamiento del Ecosistema

| Componente | Tipo de Licencia | Términos y Acceso |
| :--- | :--- | :--- |
| **`jg_agente` (Core Runtime)** | **Licencia Privada / Propietaria** | Software comercial con todos los derechos reservados. Su distribución, copia o uso sin licencia comercial explícita queda estrictamente prohibida. |
| **`jg_dashboard` (Control Plane)** | **GNU AGPL-3.0** | Código abierto copyleft de red. Garantiza que las modificaciones en el panel de control se compartan con la comunidad. |
| **`jg_agente_sdk` (SDK Público)** | **Licencia Abierta Permisiva (MIT / Apache-2.0)** | Libre de restricciones para permitir que terceros desarrollen e integren plugins propietarios o abiertos sin fricción. |
| **Plugins Oficiales de Javier Gálvez** *(ej. `jg_plugin_datosgob`, etc.)* | **GNU AGPL-3.0** | Disponibles públicamente para fomentar el desarrollo de capacidades comunitarias. |

Para consultas comerciales o acuerdos de licenciamiento a medida, contacte a través de **[https://javiergalvez.com](https://javiergalvez.com)**.
