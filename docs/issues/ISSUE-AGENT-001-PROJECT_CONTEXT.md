# Contexto de Proyecto: [ISSUE-AGENT-001] Autenticación y anti-replay en Execution Plane (GLOBAL-001)

## 1. Identificación y Estado
- **Issue ID:** ISSUE-AGENT-001 (GitLab #42)
- **Vínculo Global:** GLOBAL-001
- **Fase:** Fase Post-Auditoría (Implementación de Hallazgos Codex)
- **Prioridad:** High / Critical
- **Complejidad Estimada:** M
- **Estado:** Implementado / Verificado

## 2. Alineación Arquitectónica
En la auditoría técnica independiente (GLOBAL-001 / ITEM-AG-03), se detectó que los endpoints de ejecución (`/executions/*`) en `jg_agente` carecían de verificación criptográfica estricta contra el plano de control (`jg_dashboard`).

Para blindar el Execution Plane sin romper la separación de planos ni depender de perímetros de red:
1. **Contrato Criptográfico Canónico Compartido:**
   Toda petición a `/executions/*` debe incluir las cabeceras:
   - `X-Signature`: Firma hexadecimal HMAC-SHA256 generada con el secreto permanente (`PERMANENT_AGENT_SECRET` o `CredentialStore`).
   - `X-Timestamp`: Marca de tiempo Unix en segundos (formato entero o decimal).
   - `X-Agent-ID`: Identificador UUID del agente destinatario.
2. **Estructura de la Petición Canónica:**
   ```text
   METHOD\nPATH\nTIMESTAMP\nSHA256(RAW_BODY)
   ```
   donde el método está en mayúsculas (`POST`, `GET`), la ruta es el path normalizado (`/executions/trigger`), y el hash del cuerpo es el SHA-256 de los bytes exactos recibidos en el cable (o `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` para peticiones sin cuerpo).
3. **Defensa Anti-Replay:**
   Se descarta cualquier petición con un timestamp con desviación superior a $\pm 300$ segundos respecto al reloj del servidor del agente, respondiendo con HTTP 401 Unauthorized.
4. **Resistencia a Manipulaciones:**
   Cualquier alteración en un solo byte del body, timestamp, método o path provoca un fallo inmediato de verificación HMAC (usando `hmac.compare_digest` para evitar ataques de temporización) retornando HTTP 401.

## 3. Criterios de Aceptación
- Dependencia FastAPI `verify_control_plane_auth` aplicada a todo el router `executions_router`.
- Peticiones sin firma, con firma manipulada, con timestamp desfasado (>300s) o con `X-Agent-ID` discordante retornan 401.
- El cuerpo de la petición puede ser leído y parseado transparentemente por los endpoints downstream (`request.body()` en caché de Starlette).
- Batería de pruebas unitarias y de integración que demuestre el rechazo por manipulación de un solo byte y paso exitoso con firma canónica válida.
