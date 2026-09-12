# Contexto de Proyecto: [ISSUE-AGENT-003] Aislamiento multi-agente en persistencia y checkpoints (GLOBAL-002)

## 1. Identificación y Estado
- **Issue ID:** ISSUE-AGENT-003 (GitLab #44)
- **Vínculo Global:** GLOBAL-002
- **Fase:** Fase Post-Auditoría (Implementación de Hallazgos Codex)
- **Prioridad:** High
- **Complejidad Estimada:** S
- **Estado:** Implementado / Verificado

## 2. Alineación Arquitectónica
En el diseño de persistencia de `jg_agente`:
1. **Agnosticismo Radical del Core:**
   El código del agente (`app/`) no contiene nombres de base de datos fijos. Lee su configuración de conexión exclusivamente desde variables de entorno (`POSTGRES_DB` o `DATABASE_URL`).
2. **Aislamiento Multi-Agente por Base de Datos Dedicada:**
   Para prevenir colisiones en identificadores de hilos (`thread_id`), sobreescritura cruzada de checkpoints de LangGraph (`core_checkpoints`, `core_checkpoint_writes`, `core_checkpoint_blobs`) o interferencias entre ejecuciones (`core_executions`, `core_audit_records`), cada runtime activo dispone de su propia base de datos física dentro del servidor PostgreSQL compartido:
   - **`jg_agente_conversacional`**: Base de datos `jg_agente_conversacional`.
   - **`jg_agente_devops`**: Base de datos `jg_agente_devops`.
3. **Provisionamiento e Idempotencia:**
   El servicio `jg_agente_postgres` inicializa automáticamente ambas bases de datos mediante el script idempotente `docker/postgres/init-databases.sh` montado en `/docker-entrypoint-initdb.d/`, garantizando los permisos necesarios sin requerir múltiples instancias de servidores de base de datos ni alterar el aislamiento plane-to-plane.

## 3. Criterios de Aceptación
- La configuración en `docker-compose.yml` enruta a `jg_agente_conversacional` hacia la base de datos `jg_agente_conversacional` y a `jg_agente_devops` hacia `jg_agente_devops`.
- Script de inicialización idempotente montado en el contenedor de base de datos.
- El Core de `jg_agente` mantiene 100% de compatibilidad y agnosticismo con cualquier URI de conexión especificada.
