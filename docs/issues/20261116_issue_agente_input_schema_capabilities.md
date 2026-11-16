# Issue 04: [jg_agente] Feat: Exposición de inputSchema (JSON Schema Pydantic) en CapabilityRegistry y endpoint /capabilities

- **Título:** `[jg_agente] Feat: Exposición de inputSchema (JSON Schema Pydantic) en CapabilityRegistry y endpoint /capabilities`
- **Prioridad y Fase:** Alta | Fase 0: Remediación Base
- **Dependencias:** Ninguna
- **Contexto Técnico y Archivos Afectados:**
  - Hallazgo del informe: `H-14` (`capabilities_json` y `/capabilities` omiten el esquema de argumentos `inputSchema`, impidiendo que clientes MCP externos conozcan los tipos y parámetros de las herramientas disponibles).
  - Archivos a modificar:
    - `jg_agente/app/core/registry.py`
    - `jg_agente/app/api/telemetry.py`
    - `jg_agente/tests/test_registry_capabilities_schema.py` (Crear)

---

## Especificación Técnica

### 1. `jg_agente/app/core/registry.py`
- En el método `CapabilityRegistry.get_capabilities_summary()`:
  - Inspeccionar el atributo `args_schema` de cada instancia `AgentTool`.
  - Si `args_schema` está definido y es una subclase de `pydantic.BaseModel`, generar el esquema JSON estándar mediante `t.args_schema.model_json_schema()`.
  - Si `args_schema` es `None`, proveer un esquema de objeto abierto por defecto:
    ```json
    {
      "type": "object",
      "properties": {},
      "additionalProperties": true
    }
    ```
  - Incorporar el campo `input_schema` dentro del diccionario descriptivo de cada herramienta devuelta en `"tools"`:
    ```python
    "tools": [
        {
            "name": t.name,
            "description": t.description,
            "category": t.category,
            "risk_level": str(t.risk_level),
            "read_only": t.read_only,
            "reversible": t.reversible,
            "makes_http_requests": t.makes_http_requests,
            "input_schema": (
                t.args_schema.model_json_schema()
                if getattr(t, "args_schema", None) is not None and hasattr(t.args_schema, "model_json_schema")
                else {"type": "object", "properties": {}}
            ),
        }
        for t in self._tools.values()
    ]
    ```

### 2. `jg_agente/app/api/telemetry.py`
- Asegurar que la respuesta devuelta por el endpoint `GET /capabilities` refleje fielmente la estructura enriquecida de `input_schema` sin truncamientos ni sanitizaciones que alteren los tipos del esquema JSON.

---

## Criterios de Aceptación (Checklist Verificable)

- [ ] Test unitario en `jg_agente/tests/test_registry_capabilities_schema.py` que registra herramientas con esquemas Pydantic complejos (strings, ints, listas, enums) y comprueba que `get_capabilities_summary()["tools"][0]["input_schema"]` contiene la especificación JSON Schema OpenAPI 3.1 válida (`properties`, `required`, `type`).
- [ ] Test de endpoint con `fastapi.testclient.TestClient` o `httpx.AsyncClient` sobre `GET /capabilities` verificando el código 200 OK y la presencia íntegra de `input_schema`.
- [ ] Comprobación de que no se producen fallos de serialización al persistir o transmitir dicho esquema.
- [ ] Linters limpios: `ruff check .` en `jg_agente`.
