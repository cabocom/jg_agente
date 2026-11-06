# Contratos y Modelos Core

> **Estado del Documento:** ESPECIFICACIÓN TÉCNICA VIVA  
> **Versión:** 2.3.0  
> **Módulo:** `app.models`  

---

## 1. Contratos de Entrada y Salida (I/O)

Los modelos de I/O desacoplan el motor cognitivo de cualquier protocolo de transporte (REST, gRPC, colas de mensajería).

### 1.1 `AgentInput`
Estímulo de entrada normalizado hacia el agente:

```python
class AgentInput(BaseModel):
    execution_id: str = Field(..., description="ID único de la ejecución asignado por el invocador")
    thread_id: str = Field(..., description="ID de sesión o hilo conversacional persistente")
    prompt: str = Field(..., description="Estímulo principal de texto normalizado")
    parameters: dict[str, Any] = Field(
        default_factory=dict, description="Parámetros opcionales del contexto"
    )
    user_context: Optional[UserContext] = Field(
        default=None, description="Contexto del usuario autenticado en el Dashboard"
    )
```

### 1.2 `AgentOutput`
Respuesta final normalizada emitida por el agente:

```python
class AgentOutput(BaseModel):
    execution_id: str
    thread_id: str
    status: ExecutionStatus  # completed, waiting_approval, failed, cancelled
    response: str
    data: Optional[dict[str, Any]] = None
    execution_time_ms: float
    requires_approval: bool = False
    pending_approval_id: Optional[str] = None
    error: Optional[str] = None
```

---

## 2. Contratos de Herramientas (`AgentTool` y `ToolResult`)

> **Fuente Única de Verdad (SSOT):** Los contratos base de herramientas (`AgentTool`), resultados (`ToolResult`) y clasificaciones (`RiskLevel`, `ToolType`) se definen de forma canónica y desacoplada en el paquete **`jg_agente_sdk`** (`jg_sdk.contracts`). El Core (`app.models.tools`) hereda directamente de este contrato e implementa el adaptador hacia LangChain (`as_langchain_tool`).

Toda capacidad invocable por el agente debe satisfacer el contrato estricto `AgentTool`.

```python
class AgentTool(BaseModel):
    name: str
    description: str
    category: str
    version: str = "1.0.0"
    args_schema: type[BaseModel]
    func: Callable[..., ToolResult]
    risk_level: RiskLevel = RiskLevel.LOW
    required_permissions: list[str] = []
    tool_type: ToolType = ToolType.READ
    read_only: bool = True
    reversible: bool = False
    idempotent: bool = False
    makes_http_requests: bool = False
    timeout_sec: float = 30.0
    rollback_func: Optional[Callable[[dict[str, Any]], ToolResult]] = None
```

### 2.1 Semántica y Validación de Compensación (Rollback)
- **Regla Estricta:** Si `reversible == True`, el constructor de `AgentTool` valida obligatoriamente que `rollback_func` no sea nulo; de lo contrario, lanza `ValidationError`.
- **Emisión de Rollback No Disponible:** Si una herramienta con `reversible == False` recibe una solicitud de compensación, el sistema emite un `ToolResult` controlado con el mensaje explícito `NO_ROLLBACK_AVAILABLE`.

---

## 3. Estado Global del Grafo (`AgentState`)

Estado canónico tipado para [LangGraph](https://github.com/langchain-ai/langgraph), diseñado de forma agnóstica sin referencias a tecnologías de infraestructura:

```python
class AgentState(TypedDict, total=False):
    request: AgentInput
    messages: Annotated[list[BaseMessage], add_messages]
    intent: Optional[IntentModel]
    plan: Optional[ExecutionPlan]
    status: AgentExecutionStatus
    environment_snapshot: Optional[dict[str, Any]]
    approval: Optional[ApprovalRecord]
    current_step: int
    execution_records: Annotated[list[StepExecutionRecord], append_reducer]
    cognitive_steps: Annotated[list[CognitiveStepRecord], append_reducer]
    verification_results: Annotated[list[dict[str, Any]], append_reducer]
    audit_trail: Annotated[list[AuditRecord], append_reducer]
    errors: Annotated[list[ExecutionError], append_reducer]
    iteration: int
    max_iterations: int
    evaluation_records: Annotated[list[EvaluationRecord], append_reducer]
    is_resolved: bool
```

### 3.1 Decisiones de Seguridad (`PolicyDecision` y `SecurityEvaluationResult`)
Utilizados por el `SecurityGuard` y persistidos por el `SecurityAuditLogger`:

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

### 3.2 Evaluación Semántica de Objetivos (`GoalStatus` y `EvaluationRecord`)
Utilizados en el ciclo de razonamiento iterativo para evaluar el cumplimiento de metas y detectar capacidades ausentes:

```python
class GoalStatus(StrEnum):
    SATISFIED = "satisfied"
    NEEDS_MORE_INFO = "needs_more_info"
    BLOCKED_MISSING_CAPABILITY = "blocked_missing_capability"
    FAILED = "failed"


class EvaluationRecord(BaseModel):
    iteration: int = 1
    goal_status: GoalStatus
    explanation: str
    missing_capabilities: list[str] = []
    suggested_next_action: Optional[str] = None
    timestamp: datetime
```
