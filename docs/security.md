# Seguridad, Políticas y Auditoría Inmutable

> **Estado del Documento:** ESPECIFICACIÓN TÉCNICA VIVA  
> **Versión:** 2.3.0  
> **Módulo:** `app.security`  

---

## 1. Principio Fundamental de Seguridad

> **La seguridad de `jg_agente` no depende únicamente de filtros sintácticos o blacklists de comandos.**

El Execution Plane implementa un modelo de defensa en profundidad donde cada estímulo, decisión de riesgo y ejecución de herramienta es evaluado y auditado de forma determinista antes de su ejecución física sobre el entorno.

---

## 2. Decisiones de Seguridad Formals (`SecurityEvaluationResult`)

Toda evaluación previa a la invocación física genera un resultado tipado e inmutable:

```python
class PolicyDecision(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_HUMAN_APPROVAL = "require_human_approval"

class SecurityEvaluationResult(BaseModel):
    decision: PolicyDecision
    operation: str
    target_resource: str
    risk_level: RiskLevel
    reason: str
    required_permissions: list[str]
    is_reversible: bool
    can_cause_data_loss: bool
    evaluated_at: datetime
```

---

## 3. Servicio de Auditoría (`SecurityAuditLogger`)

El servicio [`SecurityAuditLogger`](../app/security/audit.py) es el componente central de trazabilidad y compliance del agente. Registra eventos en memoria y en la tabla `core_audit_records` de PostgreSQL.

### 3.1 Persistencia Asíncrona No Bloqueante
- Los registros se despachan como tareas en segundo plano (`asyncio.create_task`) utilizando la factoría de sesiones asíncronas de SQLAlchemy (`async_session_factory`).
- Se mantiene un registro en `_pending_tasks` para prevenir recolección prematura por el Garbage Collector.
- El método `await audit.flush()` permite esperar la sincronización de todas las tareas en vuelo antes del cierre o de emitir respuestas finales.

### 3.2 Atributos Obligatorios por Evento
Cada registro de auditoría persiste estructurado con los siguientes cuatro metadatos esenciales:
1. **`timestamp`**: Marca temporal UTC de alta precisión.
2. **`actor`**: Identificador del usuario autenticado, subagente o subsistema responsable (`security_guard`, `tool_executor`, `orchestrator`, `user_id`).
3. **`risk_level`**: Nivel de riesgo formal (`low`, `medium`, `high`, `critical`).
4. **`result`**: Resultado o veredicto de la operación (`allow`, `deny`, `success`, `failed`, `transitioned`, `approved`).

### 3.3 Métodos Semánticos de Registro
- `record_stimulus(input_data: AgentInput)`: Registra la recepción de un estímulo externo.
- `record(evaluation: SecurityEvaluationResult)`: Registra veredictos del subsistema de políticas de seguridad.
- `record_tool_execution(...)`: Registra duración, éxito, argumentos y contexto de rollback de una herramienta.
- `record_state_transition(...)`: Registra cambios de estado del ciclo operacional.
- `record_approval(...)`: Registra solicitudes y decisiones de intervención humana (HITL).
- `record_event(...)`: Registro de eventos estructurados genéricos.

### 3.4 Resiliencia ante Claves Foráneas Desacopladas
Si se audita una acción con un `execution_id` que aún no existe en `core_executions` (ej. en flujos efímeros o evaluaciones previas al registro de ejecución), el logger captura la excepción de clave foránea e inserta el registro con `execution_id=None`, preservando el identificador dentro de `details["unlinked_execution_id"]` para asegurar que **ninguna traza de auditoría se pierda jamás**.

---

## 4. Protección contra Server-Side Request Forgery (SSRF)

El módulo [`SSRFValidator`](../app/security/ssrf.py) protege al Execution Plane contra peticiones no autorizadas hacia recursos internos, interfaces de administración y metadatos de proveedores de nube.

### 4.1 Rangos y Destinos Bloqueados por Defecto
1. **Loopback:** `127.0.0.0/8`, `::1/128`.
2. **Cloud Metadata Services (IMDS):** `169.254.0.0/16`, `fe80::/10` (AWS, GCP, Azure, OpenStack `169.254.169.254`).
3. **Redes Privadas (RFC 1918 / RFC 4193):** `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `fc00::/7`.
4. **Hostnames Protegidos:** `localhost`, `metadata.google.internal`, `*.local`, `*.internal`.
5. **Esquemas No Autorizados:** Se bloquean esquemas arbitrarios (`file://`, `ftp://`, `gopher://`), autorizando exclusivamente `http` y `https`.

### 4.2 Defensa en Profundidad para `AgentTool`
- **Declaración:** Las herramientas declaran explícitamente `makes_http_requests=True` en su contrato.
- **Inspección de Argumentos (`validate_tool_arguments_for_ssrf`):** Escanea argumentos de entrada generados por LLMs detectando URLs o IPs privadas embebidas.
- **Resolución DNS y Anti-Rebinding:** Resuelve los nombres de dominio a sus direcciones IP físicas y verifica cada una de ellas contra las listas de redes bloqueadas.
- **Allowlists Configurables:**
  - `SSRF_ALLOWED_HOSTS`: Dominios o comodines autorizados (ej. `*.cabocom.net`, `api.github.com`).
  - `SSRF_ALLOWED_NETWORKS`: Subredes CIDR explícitamente autorizadas para integraciones internas (ej. `10.200.0.0/24`).
  - `SSRF_ALLOW_PRIVATE_NETWORKS`: Flag opcional de entorno para permitir redes RFC 1918 sin desbloquear jamás loopback ni cloud metadata.

