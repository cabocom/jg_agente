# Project Context: [AGENTE-SEC-04] Auto-Asignación de Permisos a Invocadores no Autorizados en risk_assess_node

## Componentes y Capas Afectadas

- **Nodo de Evaluación de Riesgos (`jg_agente/app/nodes/risk_assess.py`):**
  - Prohibición absoluta de auto-conceder `tool.required_permissions` al llamador.
  - Resolución jerárquica de permisos: `state.caller_permissions` -> `req.user_context.permissions` / `role == "admin"`.
- **Esquema de Estado (`jg_agente/app/models/state.py`):**
  - `AgentState`: inclusión del campo `caller_permissions: list[str] | None` para propagación estricta y tipada en LangGraph.

---

## Directrices de Desarrollo y Gobernanza

1. **Principio de Mínimo Privilegio en el Grafo Cognitivo:**
   - Ningún nodo del grafo debe conceder, inferir o elevar permisos en favor del invocador de forma automática o basada en la herramienta solicitada.
2. **Denegación por Defecto ante Permisos Ausentes:**
   - Si una herramienta exige permisos y el invocador no aporta contexto de autorización explícito, la operación debe ser denegada inmediatamente (`PolicyDecision.DENY`).
3. **Propagación Formal del Contexto de Seguridad:**
   - La identidad y los permisos del llamador deben viajar dentro del estado tipado (`AgentState`) o del objeto `AgentInput.user_context`, garantizando trazabilidad en el log de auditoría inmutable (`SecurityAuditLogger`).
