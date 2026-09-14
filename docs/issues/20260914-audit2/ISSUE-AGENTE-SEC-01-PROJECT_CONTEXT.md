# Project Context: [AGENTE-SEC-01] Escapada de Contenedor y Compromiso Root del Host vía Docker Socket

## Componentes y Capas Afectadas

- **Orquestación y Despliegue (`docker-compose.yml`):**
  - Servicio `jg_docker_socket_proxy`: Proxy intermediario (`tecnativa/docker-socket-proxy:latest`) que aísla el socket Unix del host (`/var/run/docker.sock:ro`) con ACLs restrictivas (`CONTAINERS=1`, `POST=1`, `VOLUMES=0`, `EXEC=0`, `NETWORKS=0`, `IMAGES=0`).
  - Servicio `jg_agente_devops`: Eliminado `user: "0:0"` (corre con usuario seguro `appuser` UID 10001), desvinculado de `/var/run/docker.sock`, configurado con `DOCKER_HOST: tcp://jg_docker_socket_proxy:2375` y vinculado a `127.0.0.1:8002`.
  - Servicio `jg_agente_conversacional`: Puerto vinculado a `127.0.0.1:8001`.
- **Plugin DevOps (`jg_agente/plugins/jg_plugin_devops`):**
  - `docker_tools.py`:
    - `get_docker_client()`: Soporte y resolución preferente de la variable de entorno `DOCKER_HOST`.
    - `PROTECTED_INFRASTRUCTURE_CONTAINERS`: Conjunto inmutable de protección contra manipulación o reinicio de los proxies de seguridad (`jg_docker_socket_proxy`, `docker_socket_proxy`).
    - `DockerRestartArgs` y `restart_container_fn`: Validación y bloqueo de contenedores protegidos de la infraestructura.

---

## Directrices de Desarrollo y Gobernanza

1. **Prohibición de Acceso Directo al Socket Unix en Producción:**
   - Ningún contenedor de agente debe montar `/var/run/docker.sock` directamente.
   - Cualquier interacción con el daemon de Docker debe canalizarse a través de un socket proxy con mínimos privilegios y en una red Docker interna.
2. **Ejecución No-Root Obligatoria:**
   - Todos los agentes cognitivos deben ejecutarse como usuarios sin privilegios (UID 10001 `appuser`). Queda terminantemente prohibido el uso de `user: "0:0"` en servicios de agentes.
3. **Restricción de Puertos en el Host:**
   - Los puertos de los agentes (`8001`, `8002`) solo deben exponerse en `127.0.0.1` para inspección en desarrollo. En producción, deben comunicarse exclusivamente a través de la red interna `jg_network` sin exposición al host.
4. **Protección de la Infraestructura de Seguridad:**
   - Las herramientas de actuación de los agentes (`ACTUATOR`) deben contener validaciones explícitas para impedir la detención o alteración de los componentes de seguridad y observabilidad que supervisan su ejecución.
