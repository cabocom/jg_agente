# Walkthrough: [AGENTE-SEC-01] Escapada de Contenedor y Compromiso Root del Host vía Docker Socket

## Resumen de Cambios

Se ha erradicado la vulnerabilidad crítica de elevación de privilegios y posible escape de contenedor en `jg_agente_devops` mediante la implementación del principio de mínimo privilegio en el acceso al motor Docker y el endurecimiento de la configuración de red y ejecución de contenedores.

---

### 1. Endurecimiento en `docker-compose.yml`

- **Despliegue de `jg_docker_socket_proxy`:**
  - Se añadió el servicio `jg_docker_socket_proxy` basado en `tecnativa/docker-socket-proxy:latest`.
  - Monta `/var/run/docker.sock` en modo solo lectura (`:ro`).
  - Habilita exclusivamente las APIs necesarias: `CONTAINERS=1`, `POST=1`, `INFO=1`, `VERSION=1`.
  - Bloquea explícitamente vectores de escalada y escape: `VOLUMES=0`, `EXEC=0`, `NETWORKS=0`, `SERVICES=0`, `IMAGES=0`, `BUILD=0`.
  - Aislado completamente dentro de `jg_network` sin exposición de puertos al host.
- **Hardening de `jg_agente_devops`:**
  - Se eliminó `user: "0:0"`, restableciendo la ejecución bajo el usuario no privilegiado `appuser:appgroup` (`UID:GID 10001:10001`).
  - Se eliminó el volumen de montaje directo `/var/run/docker.sock:/var/run/docker.sock`.
  - Se configuró la variable de entorno `DOCKER_HOST: tcp://jg_docker_socket_proxy:2375`.
  - Se añadió dependencia `jg_docker_socket_proxy` en `depends_on`.
- **Aislamiento de Puertos:**
  - Mapeo de puertos de `jg_agente_devops` y `jg_agente_conversacional` fijado a `127.0.0.1` (`127.0.0.1:8002:8000` y `127.0.0.1:8001:8000`), evitando exposición en interfaces públicas (`0.0.0.0`).

---

### 2. Cambios en `jg_agente/plugins/jg_plugin_devops/docker_tools.py`

- **Soporte de `DOCKER_HOST`:**
  - Se actualizó `get_docker_client()` para inspeccionar la variable de entorno `DOCKER_HOST` e instanciar `docker.DockerClient(base_url=docker_host, timeout=5)`.
- **Protección de Contenedores de Seguridad:**
  - Se definió el conjunto inmutable `PROTECTED_INFRASTRUCTURE_CONTAINERS` (`jg_docker_socket_proxy`, `docker_socket_proxy`).
  - Validación a nivel de esquema Pydantic (`DockerRestartArgs`) y función ejecutora (`restart_container_fn`) para impedir cualquier manipulación de la infraestructura de proxy.

---

### 3. Pruebas Unitarias

- **`tests/test_docker_tools.py`:**
  - `test_get_docker_client_with_docker_host`: Verifica que `get_docker_client()` utiliza la variable `DOCKER_HOST` para conectarse al proxy.
  - `test_restart_protected_infrastructure_container_rejected`: Verifica que los intentos de reiniciar contenedores de seguridad protegidos son rechazados tanto en validación de esquema como en tiempo de ejecución.

---

## Verificación

- **Suite de Pruebas `jg_agente`:**
  - Ruff: 106 archivos formateados y linter limpio.
  - MyPy: 0 errores en 106 archivos de código fuente.
  - Pytest: 368 tests pasados (100%).
- **Suite de Pruebas `jg_dashboard`:**
  - 255 tests pasados en Pest.
- **Verificación Global:**
  - `./check.sh` ejecutado con código de salida 0.
