# Contexto del Proyecto: AGENTE-LOGIC-01

## 1. Módulo Afectado
- **Ruta principal:** `jg_agente/app/nodes/reason.py`
- **Componentes relacionados:** `jg_agente/app/core/llm.py`, `jg_agente/app/core/graph.py`
- **Severidad:** 🟠 ALTO

---

## 2. Principio Arquitectónico Relevante: Agnosticismo Radical del Core
El Core de `jg_agente` debe permanecer totalmente agnóstico a los dominios funcionales.
Los conceptos de infraestructura, devops, telefonía, etc., residen exclusivamente en los plugins (`CapabilityRegistry`).
Hardcodear verbos de acción en `reason.py` infringía este principio.

---

## 3. Comportamiento Esperado tras la Remediación
- Los saludos y cortesía simples continúan resolviéndose de manera directa (`action_type="conclude"`).
- Las consultas operativas formuladas en lenguaje natural en español (como preguntas de lectura *"Dime el estado de los contenedores"*, *"¿Cuál es la memoria libre?"*, etc.) son analizadas por la IA y, si no emiten llamadas directas a herramientas en la primera pasada, se clasifican como `"ACTION"` derivando al motor de planificación (`action_type="plan"`).
