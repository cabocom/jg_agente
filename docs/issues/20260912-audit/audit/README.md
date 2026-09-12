# Auditoría independiente — jg_agente

Fecha: 2026-09-06. Alcance: código, plugins, configuración, Docker, persistencia y pruebas del árbol `jg_agente`. No se modificó código funcional.

## Estado general

**No apto para exponer ni para ejecutar acciones DevOps privilegiadas.** El núcleo de plugins y el flujo LangGraph están razonablemente separados del dominio, pero la API de ejecución carece de autenticación, el despliegue entrega Docker privilegiado y la persistencia no separa instancias de agente.

| Severidad | Hallazgos |
|---|---:|
| CRITICAL | 0 |
| HIGH | 3 |
| MEDIUM | 3 |
| LOW | 1 |
| INFO | 2 |

Prioridades: AGENT-001 (API sin autenticación), AGENT-002 (socket Docker + root), AGENT-003 (aislamiento multiagente). Véase [FINDINGS.md](FINDINGS.md) e [ISSUES.md](ISSUES.md).

Lo que sí está bien: registro con token de un solo uso bloqueado en transacción, contratos Pydantic, detección de conflictos en `CapabilityRegistry`, y separación física prevista entre PostgreSQL del agente y Dashboard.
