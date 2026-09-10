# Análisis Técnico: [ISSUE-AGENT-001] Autenticación y anti-replay en Execution Plane (GLOBAL-001)

## 1. Diagnóstico del Estado Previo
En el estado previo de `jg_agente`:
- El router `app/api/executions.py` exponía `/executions/trigger`, `/executions/{thread_id}`, `/executions/{thread_id}/approve` y `/executions/{thread_id}/reject` sin ningún filtro de autenticación a nivel de endpoint ni de router.
- Consecuentemente, cualquier servicio dentro de la red Docker podía emitir comandos directos al motor de ejecución sin demostrar conocimiento del secreto permanente del agente.
- Además, no existía mecanismo anti-replay ni validación de integridad del payload entre `jg_dashboard` y `jg_agente`.

## 2. Alternativas Evaluadas
1. **Bearer Token simple (`Authorization: Bearer <secret>`):**
   - *Inconveniente:* No protege la integridad del payload contra modificaciones en tránsito ni ofrece protección anti-replay ante captura de tráfico en la red interna.
2. **mTLS (Mutual TLS):**
   - *Inconveniente:* Complejidad desproporcionada para el despliegue actual con certificados autofirmados, difícil rotación en contenedores de desarrollo local.
3. **Firma Canónica HMAC-SHA256 con ventana de tiempo (Opción Seleccionada):**
   - *Ventajas:* Protección criptográfica de integridad absoluta (cualquier byte alterado invalida la firma), anti-replay determinista (ventana de 300 segundos), compatibilidad nativa con arquitecturas Zero-Trust, uso de secretos permanentes ya intercambiados en el ciclo de bootstrap.

## 3. Especificación Técnica
- Módulo: `app/security/auth.py`.
- Funciones canónicas:
  - `compute_canonical_string(method, path, timestamp, body_bytes) -> str`
  - `compute_hmac_signature(secret, canonical_string) -> str`
  - `verify_hmac_signature(secret, canonical_string, received_signature) -> bool`
  - `verify_control_plane_auth(request: Request)`: Dependencia FastAPI que:
    1. Extrae cabeceras `X-Signature`, `X-Timestamp`, `X-Agent-ID`.
    2. Valida coherencia del `X-Agent-ID` con el ID del agente configurado.
    3. Verifica que `abs(now - timestamp) <= 300` segundos.
    4. Lee `await request.body()`.
    5. Reconstruye el canonical request y verifica la firma con `hmac.compare_digest`.
- Aplicación:
  - `router = APIRouter(prefix="/executions", tags=["Executions"], dependencies=[Depends(verify_control_plane_auth)])`.
