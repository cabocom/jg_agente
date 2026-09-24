# Cierre del Issue: [REFACTOR-SDK-001] Integración Canónica de Contratos Core desde jg_agente_sdk

## 1. Conclusión y Logros
Se ha completado la refactorización arquitectónica para establecer una **Fuente Única de Verdad (SSOT)** en el ecosistema de agentes:
- El motor (`jg_agente`) ha dejado de duplicar las definiciones de `AgentTool`, `ToolResult`, `RiskLevel` y `ToolType`.
- Dichos contratos residen exclusivamente en `jg_agente_sdk` (`jg_sdk.contracts`), desacoplados de frameworks pesados y disponibles para creadores de plugins.
- El Core hereda limpiamente de estos contratos e implementa los adaptadores propios de su tecnología cognitiva (LangChain / LangGraph).
- Se ha eliminado la fragilidad en CI/CD comentando las pruebas de deriva entre repositorios y documentando las tareas pendientes para su reactivación una vez implementada la distribución de paquetes en GitLab.

## 2. Instrucciones para Despliegue y Próximos Pasos
1. **Comprobar estado git local:**
   - En `jg_agente`: commitear los cambios incluyendo esta documentación.
   - En `jg_agente_sdk`: commitear el nuevo script de check, `py.typed` y el `README.md` formateado.
2. **Crear issues de reactivación:**
   - Crear las 2 issues de seguimiento en GitLab detalladas en la especificación técnica.
