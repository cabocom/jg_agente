# Seguridad

Los controles `SecurityGuard` sí se invocan desde `execute_node`, pero son controles de herramienta, no controles de frontera HTTP. El `user_context` proviene del payload no autenticado y no puede ser una fuente de autorización confiable.

El Compose contradice el Dockerfile: éste crea `appuser`, mientras que `docker-compose.yml` fuerza `user: "0:0"` y monta `/var/run/docker.sock`. El plugin DevOps llama a `docker.from_env`; con un socket Docker, root dentro del contenedor equivale de forma práctica a control del host Docker. `cap_drop` y `no-new-privileges` no eliminan esa capacidad delegada al daemon.

Las credenciales locales se persisten con `chmod 0600`, una medida positiva, aunque la escritura no es atómica y una caída puede dejar un JSON truncado.
