## Resolución de Incidencia: [AGENTE-LOGIC-03] Omisión de caller_permissions en execute_node Causa Denegaciones Falsas

### Diagnóstico y Causa Raíz
Durante la ejecución de herramientas que no cuentan con bypass de aprobación humana (o en herramientas que se ejecutan directamente en pasos autorizados), el validador de políticas `SecurityGuard` evalúa de forma estricta los permisos del llamador (`caller_permissions`). Anteriormente, `caller_permissions` no era inyectado de forma canónica en `initial_state` ni propagado en los diccionarios de mutación de estado de `risk_assess`, `human_approval` y `execute`. Al viajar un estado intermedio o una reanudación sin estos permisos explícitos, `SecurityGuard` recibía una lista vacía, causando denegaciones falsas (`INSUFFICIENT_PERMISSIONS`) en herramientas legítimas.

### Cambios Implementados
1. **Resolución Jerárquica Determinista:**
   - Creada la función `resolve_caller_permissions(state)` en [`app/models/state.py`](file:///Users/javiergalvez/Documents/Code/javiergalvez-ia/jg_agente/app/models/state.py), con soporte para extracción desde `state.caller_permissions`, `request.user_context.permissions` (incluyendo expansión de privilegios para rol admin), `request.metadata.caller_permissions` y fallback seguro a lista vacía.
2. **Inyección en Ciclo de Disparo:**
   - En [`app/api/executions.py`](file:///Users/javiergalvez/Documents/Code/javiergalvez-ia/jg_agente/app/api/executions.py), se inicializa `caller_permissions` en `initial_state`.
3. **Propagación Inmutable en Nodos:**
   - En [`app/nodes/risk_assess.py`](file:///Users/javiergalvez/Documents/Code/javiergalvez-ia/jg_agente/app/nodes/risk_assess.py), [`app/nodes/human_approval.py`](file:///Users/javiergalvez/Documents/Code/javiergalvez-ia/jg_agente/app/nodes/human_approval.py) y [`app/nodes/execute.py`](file:///Users/javiergalvez/Documents/Code/javiergalvez-ia/jg_agente/app/nodes/execute.py), se unificó la resolución y se garantiza que `caller_permissions` viaje en las mutaciones de retorno hacia LangGraph.
4. **Verificación y Pruebas Unitarias:**
   - En [`tests/test_node_execute.py`](file:///Users/javiergalvez/Documents/Code/javiergalvez-ia/jg_agente/tests/test_node_execute.py), se añadieron tests unitarios para verificar la ejecución permitida con permisos RBAC, la denegación esperada ante falta de permisos, la resolución desde `user_context`, y la función de resolución jerárquica.

### Verificación
- Suite de nodos de `jg_agente`: 73/73 tests pasados (`pytest tests/test_node_*.py`).
- Linters y análisis de tipos: `ruff check`, `ruff format --check` y `mypy` superados al 100% sin advertencias.
- Suite global de tests del repositorio ejecutada con éxito.
