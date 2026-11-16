# Issue 05: [jg_agente] Feat: Endpoint de ejecución directa y determinista POST /tools/{tool_name}/execute

- **Título:** `[jg_agente] Feat: Endpoint de ejecución directa y determinista POST /tools/{tool_name}/execute`
- **Prioridad y Fase:** Crítica | Fase 2: Runtime Determinista
- **Dependencias:** Issue 01 (`[jg_agente_sdk] Fix: Soporte nativo para herramientas asíncronas`), Issue 04 (`[jg_agente] Feat: Exposición de inputSchema`)
- **Contexto Técnico y Archivos Afectados:**
  - Hallazgos del informe: `H-01` (`POST /api/v1/tools/*` no existe en `jg_agente`, imposibilitando llamadas deterministas directas), `H-02` (`jg_filmmaker` falla y recurre a emulación local).
  - Archivos a crear/modificar:
    - `jg_agente/app/api/tools.py` (Crear)
    - `jg_agente/app/api/__init__.py` (Modificar)
    - `jg_agente/app/main.py` (Modificar)
    - `jg_agente/tests/test_direct_tool_execution.py` (Crear)

---

## Especificación Técnica

### 1. `jg_agente/app/api/tools.py`
- Crear router con prefijo `/tools` protegido con autenticación HMAC (`verify_control_plane_auth`):
  ```python
  router = APIRouter(
      prefix="/tools",
      tags=["Tools"],
      dependencies=[Depends(verify_control_plane_auth)],
  )
  ```
- Implementar endpoint:
  ```python
  @router.post(
      "/{tool_name}/execute",
      response_model=ToolExecutionResponse,
      status_code=status.HTTP_200_OK,
      summary="Invocación directa y determinista de herramienta registrada",
  )
  async def execute_tool_endpoint(
      tool_name: str,
      payload: ToolExecutionRequest,
      request: Request,
      security_guard: SecurityGuard = Depends(get_security_guard),
  ) -> ToolExecutionResponse:
  ```
- **Esquemas de Entrada y Salida (`app/models/tools.py` o dentro del router):**
  - `ToolExecutionRequest`:
    - `arguments`: `dict[str, Any]` (parámetros para la tool).
    - `execution_id`: `str | None` (UUID de trazabilidad opcional).
    - `caller_permissions`: `list[str] | None` (permisos declarados del invocador).
    - `bypass_approval`: `bool = False`.
  - `ToolExecutionResponse`:
    - `tool_name`: `str`
    - `success`: `bool`
    - `output`: `Any` (normalizado a primitivo JSON)
    - `error`: `str | None`
    - `duration_ms`: `float`
    - `metadata`: `dict[str, Any]`
- **Flujo de Ejecución:**
  1. Obtener la herramienta del `CapabilityRegistry`:
     - Si no existe: devolver HTTP 404 (`ToolNotFoundError`).
  2. Evaluar y ejecutar a través de `SecurityGuard.execute_tool`:
     - Aplica validación de RBAC, sanitización de argumentos, y chequeo SSRF.
     - Si la herramienta tiene `risk_level in (HIGH, CRITICAL)` y no viene con aprobación explícita (`bypass_approval=False`), `SecurityGuard` deniega o marca `requires_approval=True`. En tal caso, el endpoint devuelve HTTP 403 o HTTP 409 con el detalle de la política.
  3. Registrar la ejecución física en `SecurityAuditLogger` (`core_audit_records`).
  4. Devolver la respuesta normalizada.

### 2. `jg_agente/app/main.py`
- Montar `tools_router`:
  ```python
  from app.api.tools import router as tools_router
  ...
  app.include_router(tools_router)
  ```

---

## Criterios de Aceptación (Checklist Verificable)

- [ ] Test de integración que realiza una petición firmada con HMAC a `POST /tools/{nombre}/execute` para una herramienta de bajo riesgo (`RiskLevel.LOW`) y verifica el código 200 OK con el resultado de ejecución.
- [ ] Test que verifica que una llamada a una herramienta inexistente devuelve HTTP 404 con error estructurado.
- [ ] Test que verifica que una herramienta de alto riesgo (`RiskLevel.HIGH`) devuelve bloqueo de seguridad o requisito de HITL si no se proporcionan credenciales ni bypass autorizado.
- [ ] Test que confirma que el evento de ejecución queda registrado en el buffer en memoria de `SecurityAuditLogger`.
- [ ] Linters y tests pasando en `jg_agente`: `pytest tests/test_direct_tool_execution.py`.
