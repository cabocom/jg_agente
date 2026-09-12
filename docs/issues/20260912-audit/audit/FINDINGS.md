# Findings — jg_agente

## AGENT-001 — API de ejecución y HITL sin autenticación

- **Proyecto:** jg_agente · **Severidad:** HIGH · **Categoría:** SECURITY, INTEGRATION
- **Resumen / esperado:** sólo el Control Plane autenticado debería crear, consultar o reanudar ejecuciones.
- **Observado:** `app/main.py` monta `executions_router` sin middleware; `app/api/executions.py` declara `/trigger`, `/{thread_id}`, `/{thread_id}/approve` y `/{thread_id}/reject` sin comprobación de credenciales. No existe consumo de `X-Signature`, `X-Timestamp` ni `X-Control-Plane-Secret`.
- **Causa / impacto:** el HMAC que produce Dashboard no tiene receptor. Cualquier actor con alcance de red puede ejecutar herramientas, leer prompts/resultados o aprobar/rechazar un hilo.
- **Reproducción:** iniciar el agente y enviar un `POST /executions/{thread_id}/approve` sin cabeceras de Dashboard; el router lo procesa hasta la validación de estado, no responde 401.
- **Recomendación / dependencias:** autenticar y verificar firma, timestamp, identidad de agente y anti-replay antes de cada endpoint. Coordinar con DASH-001 y GLOBAL-001.

## AGENT-002 — Contenedor DevOps privilegiado mediante Docker socket

- **Proyecto:** jg_agente · **Severidad:** HIGH · **Categoría:** SECURITY
- **Esperado:** ejecución de herramientas con privilegio mínimo y una frontera explícita frente al host.
- **Observado / evidencia:** `docker-compose.yml:31,59-63` fuerza UID 0 y monta el socket Docker; `plugins/jg_plugin_devops/docker_tools.py:45-55,188-193` obtiene cliente del daemon y reinicia contenedores.
- **Causa / impacto:** el socket permite pedir al daemon crear/montar contenedores sobre el host; una herramienta o compromiso del agente puede escalar fuera del contenedor.
- **Reproducción:** con socket disponible, `docker_restart` opera directamente contra el daemon del host.
- **Recomendación:** separar runner privilegiado con autorización acotada; no montar el socket en el agente general ni ejecutarlo root. No depende del Dashboard.

## AGENT-003 — Sin aislamiento de identidad en ejecución/checkpoints compartidos

- **Proyecto:** jg_agente · **Severidad:** HIGH · **Categoría:** ARCHITECTURE, INTEGRATION
- **Esperado:** perfiles conversacional y DevOps deben coexistir sin compartir ejecución, credencial o checkpoint.
- **Observado / evidencia:** `app/db/models.py:25-113` no guarda `agent_id`; `execute_graph_pipeline` configura LangGraph sólo con `thread_id` (`app/api/executions.py:151`); Compose usa una BD común.
- **Causa / impacto:** el mismo `thread_id` entre instancias apunta al mismo namespace de checkpoint; `execution_id` es clave global. Puede producir lectura/reanudación cruzada y estados extraños.
- **Reproducción:** dos instancias que compartan DB y envíen el mismo `thread_id`; consultar o reanudar no incluye identidad de instancia.
- **Recomendación:** decidir DB por agente o namespace/columna obligatoria, constraint e identidad en cada API. Depende de GLOBAL-002.

## AGENT-004 — Timeouts declarados no se aplican a herramientas

- **Proyecto:** jg_agente · **Severidad:** MEDIUM · **Categoría:** BUG, OPERATIONS
- **Evidencia:** `AgentTool.timeout_sec` (`app/models/tools.py:115-119`) no se usa en `run` (`159-195`); `execute_node` invoca de forma directa.
- **Impacto:** una herramienta bloqueante puede agotar worker y dejar una ejecución/HITL sin respuesta.
- **Recomendación:** imponer timeout async/síncrono y cancelar/registrar el resultado.

## AGENT-005 — Tool de noticias falla antes de los mocks por DNS/SSRF

- **Proyecto:** jg_agente · **Severidad:** MEDIUM · **Categoría:** BUG, TESTING
- **Evidencia / reproducción:** pytest produjo 2 fallos en `test_news_tool.py`; `news.py:136-140` valida DNS del RSS y lanza `SSRFValidationError` antes de `httpx.Client` mockeado.
- **Impacto:** el tool deja de ofrecer fallback en entornos sin DNS y las pruebas no son deterministas.
- **Recomendación:** hacer la política explícitamente testeable y devolver resultado de fallo/fallback según contrato, sin relajar SSRF.

## AGENT-006 — Persistencia se silencia en operaciones críticas

- **Proyecto:** jg_agente · **Severidad:** MEDIUM · **Categoría:** OBSERVABILITY, ARCHITECTURE
- **Evidencia:** `_persist_or_update_execution` captura cualquier excepción y retorna `None` (`app/api/executions.py:133-141`); el endpoint continúa.
- **Impacto:** Dashboard puede recibir éxito sin registro durable, perdiendo trazabilidad y consistencia de estado.
- **Recomendación:** clasificar errores, definir disponibilidad requerida y exponer degradación de forma verificable.

## AGENT-007 — Credenciales no se escriben atómicamente

- **Proyecto:** jg_agente · **Severidad:** LOW · **Categoría:** SECURITY, OPERATIONS
- **Evidencia:** `CredentialStore.save` usa `write_text` directo (`app/core/registration.py:60-80`).
- **Impacto / recomendación:** una interrupción puede invalidar el archivo y forzar re-registro; escribir temporal, fsync y reemplazo atómico.
