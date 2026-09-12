# Contexto de Proyecto: [ISSUE-F09-T01] Estructura del paquete jg_plugin_conversational

## 1. Identificación y Metadatos
- **Issue ID:** `ISSUE-F09-T01`
- **Fase:** `FASE 09`
- **Prioridad:** `High`
- **Complejidad Estimada:** `S`
- **Dependencias:** `ISSUE-F04-T01`
- **Componente:** `plugins/jg_plugin_conversational`

---

## 2. Propósito y Alcance
Esta tarea inaugura la **FASE 09** de `jg_agente` estableciendo la base del plugin conversacional (`jg_plugin_conversational`).
El plugin materializa el **Caso A** del MVP ("Agente Conversacional Puro") definido en la arquitectura, operando de manera completamente desacoplada del Core de ejecución y sin introducir dependencias hacia componentes de DevOps ni telefonía Asterisk.

### Criterios de Aceptación
1. El plugin se estructura como un paquete Python independiente bajo `plugins/jg_plugin_conversational/` con su propio `pyproject.toml`.
2. Expone `PLUGIN_CLASS` cumpliendo formalmente con el contrato abstracto `BasePlugin`.
3. Los tests unitarios y de integración residen en su propio paquete (`plugins/jg_plugin_conversational/tests/`).
4. El sistema de tests del Core (`pytest`) y `PluginManager` autodescubren y cargan dinámicamente el plugin y su suite de pruebas.
5. Cero referencias, imports o dependencias directas con infraestructura DevOps ni Asterisk/SIP.

---

## 3. Arquitectura del Componente
```text
jg_agente/
├── plugins/
│   └── jg_plugin_conversational/
│       ├── pyproject.toml              # Paquete independiente y entry_point jg_agente.plugins
│       ├── __init__.py                 # Exporta ConversationalPlugin y PLUGIN_CLASS
│       ├── plugin.py                   # Implementación de BasePlugin
│       └── tests/
│           ├── __init__.py
│           └── test_plugin.py          # Pruebas unitarias de aislamiento y contrato
```
