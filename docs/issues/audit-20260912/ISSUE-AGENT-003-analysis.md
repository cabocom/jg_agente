# Análisis Técnico: [ISSUE-AGENT-003] Aislamiento multi-agente en persistencia y checkpoints (GLOBAL-002)

## 1. Diagnóstico del Estado Previo
En la configuración previa de `docker-compose.yml`:
- Tanto el servicio `jg_agente_conversacional` como `jg_agente_devops` apuntaban a la misma base de datos física: `POSTGRES_DB: jg_agente`.
- Las tablas de checkpoints de LangGraph (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`) particionan únicamente por `thread_id`.
- Si dos agentes recibían peticiones con un `thread_id` idéntico o si compartían el mismo espacio de ejecución sin aislamiento a nivel de base de datos, existía riesgo de colisión o acceso a estados de ejecución cruzados.

## 2. Alternativas Evaluadas
1. **Particionado por esquema PostgreSQL (`search_path`):**
   - *Inconveniente:* Requiere configurar `options="-c search_path=..."` en SQLAlchemy y LangGraph PostgresSaver, lo que añade complejidad innecesaria a las URIs y a la creación de vistas `core_*`.
2. **Instancias separadas de contenedores PostgreSQL:**
   - *Inconveniente:* Desperdicio de memoria RAM y puertos en el host (levantar dos motores PostgreSQL cuando uno solo puede albergar múltiples bases de datos).
3. **Bases de datos lógicas independientes en el mismo servidor PostgreSQL (Opción Seleccionada):**
   - *Ventajas:* Aislamiento completo, cero riesgo de colisión, cero cambios en el código de la aplicación (el Core es agnóstico y lee la URI de conexión), y uso óptimo de recursos de infraestructura compartiendo el mismo proceso motor de PostgreSQL.

## 3. Implementación
- Se definió el script idempotente `docker/postgres/init-databases.sh` que crea `jg_agente_conversacional` y `jg_agente_devops` utilizando la directiva `\gexec` de `psql` para evitar errores si las bases de datos ya existen.
- Se montó el script en `/docker-entrypoint-initdb.d/init-databases.sh:ro` dentro de `jg_agente_postgres`.
- Se parametrizaron las variables `POSTGRES_DB` y `DATABASE_URL` para cada servicio en `docker-compose.yml`.
