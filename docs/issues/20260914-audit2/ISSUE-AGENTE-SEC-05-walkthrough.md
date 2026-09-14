# Walkthrough de Implementación - Issue [AGENTE-SEC-05]

## Resumen de Cambios

Se ha implementado el control de privilegios granular para la reanudación de ejecuciones tras aprobación humana (HITL), evitando que la autorización de un paso se propague masivamente al resto del plan.

### Archivos Modificados
- `jg_agente/app/models/state.py`:
  - Enriquecido `ApprovalRecord` con `approved_step_ids: list[str] = Field(default_factory=list)` y `approved_tool_names: list[str] = Field(default_factory=list)`.
  - Añadidos los campos correspondientes a `AgentState`.
- `jg_agente/app/nodes/risk_assess.py`:
  - Se recopilan los `step_id` y `tool_name` de los pasos que originan `REQUIRE_HUMAN_APPROVAL` o `RiskLevel >= HIGH`.
  - Se inicializa `ApprovalRecord` con estas listas.
- `jg_agente/app/nodes/human_approval.py`:
  - Se extraen y preservan `approved_step_ids` y `approved_tool_names` a través de los diversos canales de entrada (payload de resume, objeto previo en estado, etc.).
- `jg_agente/app/nodes/execute.py`:
  - En lugar de aplicar `bypass_approval` ciegamente a cada iteración, se calcula `step_bypass_approval = (step.step_id in approved_step_ids or step.tool_name in approved_tool_names)`.
  - Se delegan las listas y el `step_id` a `SecurityGuard.execute_tool(...)`.
- `jg_agente/app/security/guard.py`:
  - En `execute_tool`, se calcula `effective_bypass` validando la pertenencia del paso o de la herramienta a las listas aprobadas antes de conceder bypass.
- `jg_agente/tests/test_node_execute.py`:
  - Añadido `test_execute_node_granular_hitl_approval_blocks_unapproved_step`: verifica que un paso de alto riesgo aprobado se ejecute pero un segundo paso crítico no aprobado sea bloqueado con `REQUIRE_HUMAN_APPROVAL`.
  - Añadido `test_execute_node_allows_all_when_all_steps_approved`: verifica que múltiples pasos aprobados completen normalmente.

---

## Verificación de Calidad y Pruebas

1. **Pruebas Específicas:**
   ```bash
   ./jg_agente/.venv/bin/pytest jg_agente/tests/test_node_execute.py
   # 13 passed in 0.59s
   ```

2. **Pruebas de API HITL:**
   ```bash
   ./jg_agente/.venv/bin/pytest jg_agente/tests/test_api_executions_hitl.py
   # 6 passed in 0.20s
   ```

3. **Suite Completa del Agente:**
   ```bash
   ./jg_agente/.venv/bin/pytest jg_agente/tests
   # 306 passed in 33.05s
   ```

4. **Linting y Tipado Estático:**
   ```bash
   ./jg_agente/.venv/bin/ruff check jg_agente/app jg_agente/tests jg_agente/plugins
   # All checks passed!
   ./jg_agente/.venv/bin/ruff format --check jg_agente/app jg_agente/tests jg_agente/plugins
   # 106 files already formatted
   ./jg_agente/.venv/bin/mypy --config-file jg_agente/pyproject.toml jg_agente/app jg_agente/tests jg_agente/plugins
   # Success: no issues found in 106 source files
   ```
