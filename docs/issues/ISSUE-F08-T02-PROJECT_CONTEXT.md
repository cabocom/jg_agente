# Contexto de Proyecto: [ISSUE-F08-T02] Mecanismo de persistencia y recarga de credencial permanente

**Componente:** `jg_agente` (Execution Plane)  
**Versión de Proyecto:** 2.24.0  
**Fecha:** 5 de septiembre de 2026  

---

## 1. Impacto Arquitectónico

La implementación de `[ISSUE-F08-T02]` completa el ciclo de vida de **Gestión Segura de Credenciales** entre el Execution Plane y el Control Plane:
- **Autonomía Operativa en Reinicios:** El agente puede reiniciarse tantas veces como sea necesario (por actualizaciones de software, escalado de contenedores o reinicios del host) sin requerir intervención humana ni re-aprovisionamiento de tokens.
- **Validación Activa de Integridad:** Al arrancar con una credencial permanente previamente almacenada, el agente valida activamente su identidad con el Dashboard mediante una invocación autenticada a `/agents/heartbeat`, asegurando que no opere con credenciales revocadas o desincronizadas.
- **Limpieza Automática y Prevención de Desincronizaciones:** Si el Dashboard notifica que la credencial ya no es válida (HTTP 401), el agente elimina automáticamente el archivo local para evitar bucles erróneos y alertar inmediatamente a los operadores.
- **Resiliencia ante Particiones de Red:** Si el Dashboard experimenta una caída temporal durante el arranque del agente, este no aborta el proceso, sino que inicia en modo de degradación tolerante (`verified=False`) hasta que el bucle de telemetría restablezca el enlace.

---

## 2. Puntos de Integración

- **Modelos:** `app/models/registration.py` (`AgentCredentials.verified`).
- **Core:** `app/core/registration.py` (`DashboardRegistrationClient.verify_credentials`, `reload_credentials`, `auto_register_agent`).
- **Configuración:** `app/core/config.py` (`VERIFY_CREDENTIALS_ON_BOOT`).
- **Ciclo de Vida:** `app/main.py` (`lifespan`, `root`).
- **Suite de Pruebas:** `tests/test_registration_client.py`.
