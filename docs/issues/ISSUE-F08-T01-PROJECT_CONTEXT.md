# Contexto de Proyecto: [ISSUE-F08-T01] Cliente de registro con jg_dashboard mediante bootstrap token

**Componente:** `jg_agente` (Execution Plane)  
**Versión de Proyecto:** 2.23.0  
**Fecha:** 5 de septiembre de 2026  

---

## 1. Impacto Arquitectónico

La implementación de `[ISSUE-F08-T01]` materializa el protocolo de **Aprovisionamiento Zero-Trust** en el Execution Plane:
- **Desacoplamiento del Despliegue:** El agente puede arrancarse en entornos aislados o contenedores efímeros sin requerir credenciales maestras predefinidas; solo requiere un `AGENT_BOOTSTRAP_TOKEN` efímero emitido por el Control Plane (`jg_dashboard`).
- **Persistencia Segura en el Host:** El secreto permanente recibido (`permanent_agent_secret`) se guarda en un archivo restringido con permisos `0600`, impidiendo el acceso a otros usuarios del sistema o procesos sin privilegios.
- **Idempotencia y Eficiencia:** En arranques sucesivos, el agente detecta sus credenciales en disco o en variables de entorno y no contacta de nuevo para consumir tokens innecesarios, minimizando la carga en el Dashboard.
- **Transparencia en Modo Local:** Si no se suministra token ni credenciales y la directiva `REQUIRE_DASHBOARD_REGISTRATION=False`, el agente continúa funcionando de forma local y autónoma, permitiendo suites de pruebas continuas sin infraestructura auxiliar.

---

## 2. Puntos de Integración

- **Modelos:** `app/models/registration.py` (`AgentRegistrationPayload`, `AgentRegistrationResponse`, `AgentCredentials`).
- **Core:** `app/core/registration.py` (`CredentialStore`, `DashboardRegistrationClient`, `auto_register_agent`).
- **Configuración:** `app/core/config.py` (`DASHBOARD_URL`, `AGENT_BOOTSTRAP_TOKEN`, `PERMANENT_AGENT_SECRET`, `CREDENTIALS_FILE`).
- **Ciclo de Vida:** `app/main.py` (`lifespan`, `root`).
- **Suite de Pruebas:** `tests/test_registration_client.py`.
