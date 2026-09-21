## Resolución de Incidencia: [AGENTE-LOGIC-04] Contención Secuencial Rígida Aborta Todo el Plan Ante el Primer Fallo

### Diagnóstico y Causa Raíz
El bucle de ejecución de herramientas (`execute_node`) abortaba incondicionalmente cualquier plan ante el primer fallo mediante una instrucción `break`, sin comprobar si el paso o la herramienta en ejecución era de naturaleza diagnóstica, opcional o tolerante a fallos (`allow_failure`). Esto impedía que se recabara la evidencia restante del plan y obstaculizaba la capacidad del bucle reflexivo (`evaluate -> reason -> plan`) para explorar vías alternativas de remediación.

### Cambios Implementados
1. **Esquema de Datos Tipado:**
   - Añadido el atributo `allow_failure: bool = Field(default=False)` al modelo `PlanStep` en [`app/models/state.py`](../../../app/models/state.py).
   - Añadido el atributo `allow_failure: bool = Field(default=False)` al modelo `AgentTool` en [`app/models/tools.py`](../../../app/models/tools.py).
2. **Ejecución Flexible en `execute_node`:**
   - En [`app/nodes/execute.py`](../../../app/nodes/execute.py), se evalúa la tolerancia a fallos tanto a nivel del paso como de la herramienta.
   - Si el paso permite fallos (`allow_failure=True`), se registra el error con `fatal=False` y se continúa con la ejecución de los pasos restantes en lugar de invocar `break`.
   - Si no permite fallos (`allow_failure=False`), se detiene la secuencia manteniendo la contención segura para pasos críticos.
3. **Planificación y Fallbacks:**
   - En [`app/nodes/plan.py`](../../../app/nodes/plan.py), se preserva `allow_failure` en la formulación de pasos fallback.
4. **Verificación y Pruebas Unitarias:**
   - En [`tests/test_node_execute.py`](../../../tests/test_node_execute.py), se agregaron 4 pruebas unitarias que validan la continuidad ante fallos tolerados, el aborto ante fallos críticos, el respeto al flag a nivel de herramienta y la tolerancia a herramientas no registradas.

### Verificación
- Suite de nodos de `jg_agente`: 77/77 tests pasados (`pytest tests/test_node_*.py`).
- Linters y análisis de tipos: `ruff check`, `ruff format --check` y `mypy` superados al 100% sin observaciones.
- Suite global de verificación `./check_unit.sh` superada al 100%.
