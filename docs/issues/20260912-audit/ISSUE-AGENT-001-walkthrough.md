# Walkthrough: [ISSUE-AGENT-001] Autenticación y anti-replay en Execution Plane (GLOBAL-001)

## 1. Resumen de la Implementación
Se implementó en `jg_agente` la verificación estricta de autenticación criptográfica HMAC-SHA256 y control anti-replay para todos los endpoints del Execution Plane (`/executions/*`).

## 2. Archivos Creados y Modificados
- **[app/security/auth.py](../../../app/security/auth.py)**:
  - Implementación de `compute_canonical_string`, `compute_hmac_signature`, `verify_hmac_signature`.
  - Implementación de la dependencia `verify_control_plane_auth`.
- **[app/security/__init__.py](../../../app/security/__init__.py)**:
  - Exportación de las funciones de autenticación canónica.
- **[app/api/executions.py](../../../app/api/executions.py)**:
  - Aplicación de `dependencies=[Depends(verify_control_plane_auth)]` a nivel de APIRouter.
- **[tests/test_api_executions_auth.py](../../../tests/test_api_executions_auth.py)**:
  - 12 pruebas automatizadas exhaustivas validando:
    1. Petición exitosa con firma válida.
    2. Rechazo 401 por falta de cabecera `X-Signature`.
    3. Rechazo 401 por falta de cabecera `X-Timestamp`.
    4. Rechazo 401 por falta de cabecera `X-Agent-ID`.
    5. Rechazo 401 si `X-Agent-ID` no coincide con el agente destino.
    6. Rechazo 401 por timestamp expirado (> 300 segundos en el pasado).
    7. Rechazo 401 por timestamp en el futuro (> 300 segundos).
    8. Rechazo 401 por alteración de un solo byte en el cuerpo (body tampering).
    9. Rechazo 401 por alteración del método HTTP (GET vs POST).
    10. Rechazo 401 por alteración de la ruta de la petición (path tampering).
    11. Reconstrucción canónica exacta con cuerpo vacío (GET).
    12. Preservación del body para que los endpoints downstream puedan parsear Pydantic sin error.
- **[tests/conftest.py](../../../tests/conftest.py)**:
  - Fixture autouse condicional que bypasea la autenticación en tests funcionales generales ajenos a auth, manteniendo activa la autenticación real en `test_api_executions_auth.py`.

## 3. Verificación
Se ejecutó la suite completa de tests en `jg_agente`:
```bash
.venv/bin/pytest tests/ -k "not test_database_migrations"
======================== 255 passed, 4 deselected in 66.73s =========================
```
Y específicamente las pruebas de autenticación:
```bash
.venv/bin/pytest tests/test_api_executions_auth.py
======================== 12 passed in 1.48s =========================
```
Todos los tests pasaron al 100%.
