# Análisis Técnico: [AGENTE-SEC-01] Escapada de Contenedor y Compromiso Root del Host vía Docker Socket

## Metadatos
- **Issue ID:** [jg_agente#57](https://gitlab.com/javiergalvez-ia/jg_agente/-/work_items/57)
- **Severidad:** 🔴 CRÍTICO
- **CWE:** CWE-250 (Execution with Unnecessary Privileges)
- **Componentes Afectados:**
  - `docker-compose.yml` (`jg_agente_devops`, `jg_agente_conversacional`, nuevo servicio `jg_docker_socket_proxy`)
  - `jg_agente/plugins/jg_plugin_devops/docker_tools.py` (`get_docker_client`, `PROTECTED_INFRASTRUCTURE_CONTAINERS`)
- **Fecha:** Septiembre 2026

---

## 1. Descripción del Problema

El contenedor `jg_agente_devops` se ejecutaba explícitamente como superusuario (`user: "0:0"`), exponía el puerto de servicio en todas las interfaces de red del host (`0.0.0.0:8002` mediante la directiva `"${AGENT_DEVOPS_PORT:-8002}:8000"`) y mantenía un montaje de bind directo del socket Unix del motor Docker del anfitrión (`/var/run/docker.sock:/var/run/docker.sock`).

### Causa Raíz Técnica:
1. **Acceso Sin Restricciones al Daemon Docker:** El socket `/var/run/docker.sock` otorga control administrativo absoluto sobre el motor de contenedores del host. A través de este socket, cualquier cliente puede crear nuevos contenedores con privilegios elevados (`--privileged`), montando cualquier parte del sistema de archivos del anfitrión (por ejemplo, `-v /:/host`).
2. **Ejecución Innecesaria como Root (`0:0`):** Aunque el `Dockerfile` de `jg_agente` implementa una arquitectura segura de dos etapas (`builder`/`runner`) que crea y conmuta al usuario no-root `appuser:appgroup` (`UID:GID 10001:10001`), el archivo `docker-compose.yml` anulaba esta protección con `user: "0:0"` para poder leer el socket `/var/run/docker.sock` (cuyo propietario en Linux suele ser root).
3. **Exposición en Todas las Interfaces (0.0.0.0):** Los puertos de ambos agentes (`8001` y `8002`) estaban mapeados sin vincular explícitamente a `127.0.0.1`, permitiendo que tráfico externo no autenticado desde redes públicas o perimetrales pudiera alcanzar los agentes sin pasar por el Control Plane (`jg_dashboard`).
4. **Riesgo de Inyección Prompt y Escape del Contenedor:** Un atacante que lograra una inyección de prompts indirecta en el LLM o una vulnerabilidad de ejecución remota podría manipular las llamadas de Docker para obtener acceso root en el host físico (Container Breakout).

---

## 2. Impacto Técnico y Operativo

- **Confidencialidad:** Crítica. Acceso total de lectura a todos los archivos del host, secretos de infraestructura, variables de entorno y bases de datos.
- **Integridad:** Crítica. Posibilidad de modificar binarios del sistema, instalar puertas traseras o alterar configuraciones del sistema operativo anfitrión.
- **Disponibilidad:** Crítica. Capacidad de apagar el host, eliminar volúmenes y destruir todos los servicios desplegados.

---

## 3. Solución Arquitectónica Implementada

Se ha aplicado el principio de mínimo privilegio (*Least Privilege*) y defensa en profundidad:

### A. Introducción de `jg_docker_socket_proxy`
Se despliega un proxy de seguridad intermedio utilizando la imagen oficial y contrastada `tecnativa/docker-socket-proxy:latest`:
- **Montaje de Solo Lectura del Socket:** `/var/run/docker.sock:/var/run/docker.sock:ro`.
- **Aislamiento de Red Interno:** El contenedor no expone puertos al anfitrión (`ports` omitido), residiendo exclusivamente en `jg_network`.
- **Autorización Granular Estricta (HAProxy ACLs):**
  - Habilitados:
    - `CONTAINERS=1` (inspección, listado, logs y estado).
    - `POST=1` (necesario exclusivamente para la invocación de reinicio `/containers/{id}/restart`).
    - `INFO=1`, `VERSION=1`.
  - Deshabilitados y bloqueados a nivel de proxy (HTTP 403 Forbidden):
    - `VOLUMES=0`: Impide crear o manipular volúmenes de almacenamiento en el host.
    - `EXEC=0`: Bloquea la inyección de comandos arbitrarios (`docker exec`) dentro de contenedores.
    - `BUILD=0`: Bloquea la construcción de imágenes maliciosas.
    - `IMAGES=0`: Bloquea descarga o eliminación de imágenes.
    - `NETWORKS=0`, `SERVICES=0`, `SWARM=0`, `TASKS=0`, `SYSTEM=0`: Bloquea reconfiguración de la red o del daemon de Docker.

### B. Hardening de `jg_agente_devops`
- **Eliminación de `user: "0:0"`:** El contenedor hereda la directiva segura del `Dockerfile` y corre con el usuario no privilegiado `appuser` (`10001:10001`).
- **Eliminación del Montaje Directo del Socket:** Se elimina `/var/run/docker.sock:/var/run/docker.sock`.
- **Conexión TCP Segura:** Se inyecta `DOCKER_HOST: tcp://jg_docker_socket_proxy:2375`.
- **Dependencia de Orquestación:** Añadida dependencia `depends_on: jg_docker_socket_proxy`.

### C. Aislamiento de Puertos en Localhost
- Los mapeos de puertos de `jg_agente_devops` y `jg_agente_conversacional` se vinculan explícitamente a `127.0.0.1`:
  - `127.0.0.1:${AGENT_DEVOPS_PORT:-8002}:8000`
  - `127.0.0.1:${AGENT_CONVERSATIONAL_PORT:-8001}:8000`
- Esto garantiza que ningún actor externo pueda enviar tráfico directamente a los agentes sin atravesar el Control Plane `jg_dashboard`.

### D. Protección en Código (`docker_tools.py`)
- Se implementó la resolución dinámica de `DOCKER_HOST` en `get_docker_client()` instanciando `docker.DockerClient(base_url=docker_host, timeout=5)`.
- Se definió `PROTECTED_INFRASTRUCTURE_CONTAINERS = frozenset({"jg_docker_socket_proxy", "docker_socket_proxy"})`.
- Se bloquea en el validador Pydantic `DockerRestartArgs` y en la función `restart_container_fn` cualquier intento de manipular o reiniciar los contenedores de infraestructura de seguridad.
