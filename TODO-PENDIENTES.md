# TAREAS PENDIENTES Y DEUDA TÉCNICA: jg_agente

**Proyecto:** `jg_agente` (Execution Plane)  
**Versión actual:** 2.26.0  
**Fecha de consolidación:** 6 de septiembre de 2026  
**Auditoría de referencia:** Auditoría Técnica y Diagnóstico de Arquitectura Independiente (Codex)

---

## 1. Resumen Ejecutivo de Pendientes

El motor de ejecución `jg_agente` ha completado con éxito sus fases nucleares (Fases 01 a 11), contando con una suite de **312 tests automatizados pasando al 100%**, arquitectura agnóstica basada en LangGraph, aislamiento de plugins especializados (`jg_plugin_conversational` y `jg_plugin_devops`), cliente de registro Zero-Trust y persistencia Core sobre PostgreSQL (`jg_agente_postgres`:5433).

No obstante, la auditoría exhaustiva del código fuente revela cinco ítems pendientes de resolución o deuda técnica arquitectónica:

| ID | Título | Criticidad | Estado | Componente Afectado |
| :--- | :--- | :--- | :--- | :--- |
| **ITEM-AG-01** | Migraciones DDL automáticas para modelos ORM de Plugins | MEDIA | `PENDIENTE` | `alembic/`, `plugins/jg_plugin_devops/` |
| **ITEM-AG-02** | Aislamiento y proxy de seguridad para el socket Docker (`/var/run/docker.sock`) | ALTA | `PENDIENTE / RIESGO` | `docker-compose.yml`, `plugins/jg_plugin_devops/` |
| **ITEM-AG-03** | Autenticación estricta en endpoints de ejecución (`/executions/*`) | MEDIA | `PARCIALMENTE IMPLEMENTADO` | `app/api/executions.py` |
| **ITEM-AG-04** | Orquestación multi-agente e invocación delegada (`AgentProxy`) | BAJA | `NO IMPLEMENTADO` (Post-MVP) | `app/core/` |
| **ITEM-AG-05** | Entorno de ejecución de tests (`pytest`) en imagen Docker de desarrollo | BAJA | `PENDIENTE` | `Dockerfile`, CI/CD |

---

## 2. Detalle de Ítems Pendientes

### ITEM-AG-01: Migraciones DDL automáticas para modelos ORM de Plugins
- **Severidad:** MEDIA
- **Estado:** `PENDIENTE`
- **Comportamiento Esperado:**
  Los plugins que definan modelos de base de datos relacional (como `devops_infra_snapshots` y `devops_circuit_breakers` en `plugins/jg_plugin_devops/models/orm.py`) deben contar con un mecanismo de migración DDL automático (mediante Alembic o scripts de bootstrap del plugin) para que sus tablas se creen en la base de datos `jg_agente_postgres` sin intervención manual de DBAs.
- **Comportamiento Actual:**
  El entorno de Alembic (`alembic/env.py`) filtra estrictamente las tablas para sincronizar únicamente aquellas cuyo nombre comience por `core_` (`core_executions`, `core_audit_records`). Los modelos ORM de los plugins quedan completamente ignorados por Alembic y sus tablas no existen en la base de datos física hasta que se ejecute un DDL manual.
- **Acciones Necesarias para Resolución:**
  1. Diseñar un ciclo de vida en `BasePlugin.on_startup()` o un subcomando Alembic por plugin que detecte si el plugin aporta tablas con su prefijo autorizado (`devops_*`).
  2. Ejecutar la creación o migración declarativa de dichas tablas de forma no disruptiva para el Core.
- **Archivos de Referencia:**
  - [alembic/env.py](file:///Users/javiergalvez/Documents/Code/javiergalvez-ia/jg_agente/alembic/env.py)
  - [plugins/jg_plugin_devops/models/orm.py](file:///Users/javiergalvez/Documents/Code/javiergalvez-ia/jg_agente/plugins/jg_plugin_devops/models/orm.py)
  - [docs/database.md](file:///Users/javiergalvez/Documents/Code/javiergalvez-ia/jg_agente/docs/database.md)

---

### ITEM-AG-02: Aislamiento y proxy de seguridad para el socket Docker (`/var/run/docker.sock`)
- **Severidad:** ALTA (Riesgo de Seguridad)
- **Estado:** `PENDIENTE / RIESGO`
- **Comportamiento Esperado:**
  El contenedor que ejecuta tareas de DevOps (`jg_agente_devops`) no debe tener acceso directo de lectura/escritura como `root` al socket Docker del host, o en su defecto debe intermediar las llamadas a través de un proxy restringido (como `docker-socket-proxy`) que bloquee operaciones no permitidas (ej. creación de contenedores privilegiados, montaje de volúmenes raíz, ejecución de comandos destructivos).
- **Comportamiento Actual:**
  En el archivo de despliegue `docker-compose.yml`, el servicio `jg_agente_devops` monta directamente `/var/run/docker.sock:/var/run/docker.sock:ro` o `:rw` con directiva `user: "0:0"` (root). Cualquier vulnerabilidad de ejecución remota de código en las herramientas del agente otorgaría escalado de privilegios total al host Docker.
- **Acciones Necesarias para Resolución:**
  1. Evaluar la reintroducción de un contenedor intermediario `docker-socket-proxy` con perfil de solo lectura o comandos específicos autorizados (`CONTAINERS=1`, `POST=1` para reinicios controlados).
  2. Crear un perfil no-root en el contenedor `jg_agente_devops` perteneciente únicamente al grupo `docker`.
- **Archivos de Referencia:**
  - [docker-compose.yml](file:///Users/javiergalvez/Documents/Code/javiergalvez-ia/docker-compose.yml)
  - [plugins/jg_plugin_devops/tools/docker_tools.py](file:///Users/javiergalvez/Documents/Code/javiergalvez-ia/jg_agente/plugins/jg_plugin_devops/tools/docker_tools.py)
  - [docs/security.md](file:///Users/javiergalvez/Documents/Code/javiergalvez-ia/jg_agente/docs/security.md)

---

### ITEM-AG-03: Autenticación estricta en endpoints de ejecución (`/executions/*`)
- **Severidad:** MEDIA
- **Estado:** `PARCIALMENTE IMPLEMENTADO`
- **Comportamiento Esperado:**
  Toda petición entrante a los endpoints `POST /executions/trigger`, `GET /executions/{thread_id}`, `POST /executions/{thread_id}/approve` y `POST /executions/{thread_id}/reject` debe exigir obligatoriamente una cabecera de autenticación con el secreto permanente (`Authorization: Bearer <permanent_secret>`) o firma HMAC, validada contra el almacén local seguro (`CredentialStore`).
- **Comportamiento Actual:**
  Los endpoints de la API de ejecuciones confían implícitamente en el perímetro de red privada de Docker. La cabecera `Authorization` se inspecciona de manera opcional o se omite en peticiones internas directas, lo que permitiría a cualquier contenedor en la misma red disparar ejecuciones arbitrarias si la red no está adecuadamente aislada.
- **Acciones Necesarias para Resolución:**
  1. Añadir una dependencia FastAPI de seguridad estricta (`verify_control_plane_auth`) a nivel del router `executions_router`.
  2. Contrastar el token recibido con el secreto permanente cargado en `CredentialStore`.
- **Archivos de Referencia:**
  - [app/api/executions.py](file:///Users/javiergalvez/Documents/Code/javiergalvez-ia/jg_agente/app/api/executions.py)
  - [app/core/credentials.py](file:///Users/javiergalvez/Documents/Code/javiergalvez-ia/jg_agente/app/core/credentials.py)

---

### ITEM-AG-04: Orquestación multi-agente e invocación delegada (`AgentProxy`)
- **Severidad:** BAJA
- **Estado:** `NO IMPLEMENTADO` (Post-MVP)
- **Comportamiento Esperado:**
  Capacidad para que una instancia de agente (`jg_agente_conversacional`) pueda delegar subtareas complejas a otro agente especializado (`jg_agente_devops`) mediante un contrato formal `AgentProxy`, manteniendo la correlación del `thread_id` y trazabilidad en el Dashboard.
- **Comportamiento Actual:**
  El diseño actual asume que toda orquestación multi-agente es coordinada por el Control Plane (`jg_dashboard`). Cada contenedor `jg_agente` opera de forma completamente autónoma e independiente.
- **Acciones Necesarias para Resolución:**
  1. Definir contrato `AgentProxyTool` para invocar APIs de agentes pares autorizados.
  2. Implementar paso de contexto y propagación de trazas distribuidas (OpenTelemetry trace context).
- **Archivos de Referencia:**
  - [docs/architecture.md](file:///Users/javiergalvez/Documents/Code/javiergalvez-ia/jg_agente/docs/architecture.md)

---

### ITEM-AG-05: Entorno de ejecución de tests (`pytest`) en imagen Docker de desarrollo
- **Severidad:** BAJA
- **Estado:** `PENDIENTE`
- **Comportamiento Esperado:**
  Poder ejecutar la suite de 312 tests directamente dentro de un contenedor en ejecución mediante `docker exec <container> pytest`.
- **Comportamiento Actual:**
  El Dockerfile multi-stage instala únicamente el paquete en modo producción (`pip install --no-cache-dir .`), omitiendo las dependencias opcionales de desarrollo y pruebas declaradas en `pyproject.toml` (`[project.optional-dependencies] test = [...]`). Para correr los tests, se debe utilizar el entorno virtual local de desarrollo (`.venv`) en el host:
  ```bash
  .venv/bin/pytest tests/ plugins/
  ```
- **Acciones Necesarias para Resolución:**
  1. Crear un target multi-stage en el Dockerfile (`development` o `test`) que ejecute `pip install .[test]` para permitir diagnósticos y pruebas in-container.
- **Archivos de Referencia:**
  - [Dockerfile](file:///Users/javiergalvez/Documents/Code/javiergalvez-ia/jg_agente/Dockerfile)
  - [pyproject.toml](file:///Users/javiergalvez/Documents/Code/javiergalvez-ia/jg_agente/pyproject.toml)
