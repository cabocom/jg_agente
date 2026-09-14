## Resolución y Cierre de Issue: [AGENTE-SEC-01] Escapada de Contenedor y Compromiso Root del Host vía Docker Socket

Se ha mitigado de forma exhaustiva el riesgo de escape de contenedor y elevación de privilegios en el host:

### Resumen de Cambios Implementados:

1. **Eliminación del Montaje de Socket y Usuario Root en `docker-compose.yml`:**
   - Se eliminó `user: "0:0"` en `jg_agente_devops`, restableciendo la ejecución bajo el usuario no-root `appuser` (UID 10001) configurado en el `Dockerfile`.
   - Se eliminó el montaje directo del socket Unix `/var/run/docker.sock`.
   - Se configuró la variable de entorno `DOCKER_HOST: tcp://jg_docker_socket_proxy:2375`.

2. **Despliegue de `jg_docker_socket_proxy` con Autorización Granular:**
   - Incorporado el servicio `jg_docker_socket_proxy` (`tecnativa/docker-socket-proxy:latest`) conectado al socket del host en modo solo lectura (`:ro`).
   - Restringidas las capacidades de la API de Docker a mínimos privilegios: `CONTAINERS=1`, `POST=1`, `INFO=1`, `VERSION=1`.
   - Bloqueo total de capacidades destructivas o de escape: `VOLUMES=0`, `EXEC=0`, `NETWORKS=0`, `IMAGES=0`, `BUILD=0`, `SERVICES=0`, `SWARM=0`, etc.
   - Aislado completamente dentro de `jg_network` sin exposición de puertos hacia el host.

3. **Restricción de Interfaces de Red:**
   - Se vincularon los puertos de ambos agentes (`jg_agente_devops` y `jg_agente_conversacional`) exclusivamente a `127.0.0.1` (`8002` y `8001`), impidiendo el acceso desde interfaces públicas (`0.0.0.0`).

4. **Defensa en Profundidad en `docker_tools.py`:**
   - Soporte dinámico de `DOCKER_HOST` en `get_docker_client()`.
   - Inclusión de `PROTECTED_INFRASTRUCTURE_CONTAINERS` para bloquear cualquier intento de manipular o reiniciar los proxies de seguridad.

5. **Verificación y Pruebas:**
   - 2 nuevos tests unitarios en `test_docker_tools.py` validando conexión vía `DOCKER_HOST` y rechazo de manipulación de contenedores de seguridad protegidos.
   - Suite completa de `jg_agente` superada: **368 passed** (Ruff y MyPy 0 errores en 106 archivos).
   - Suite completa de `jg_dashboard` superada: **255 passed (1222 assertions)**.
   - Script `./check.sh` ejecutado con éxito total.

---
**Commits Asociados:**
- `fix(security): mitigar escape de contenedor implementando docker-socket-proxy y usuario no-root (AGENTE-SEC-01)`
