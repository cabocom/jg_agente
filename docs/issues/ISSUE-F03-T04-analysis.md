# Análisis Técnico: ISSUE-F03-T04 — Implementación de validador de protección SSRF para tools de red

> **Issue ID:** ISSUE-F03-T04  
> **Fase:** FASE 03 (Persistencia y Checkpointing)  
> **Prioridad:** High  
> **Complejidad:** S  
> **Estado:** Implementado y Verificado  

---

## 1. Contexto y Objetivos

En sistemas basados en LLMs donde los modelos generan argumentos para herramientas con capacidades de red (`makes_http_requests=True`), existe el riesgo crítico de **Server-Side Request Forgery (SSRF)**:
Un atacante podría inducir al LLM a solicitar recursos internos como metadatos de proveedores de nube (`169.254.169.254`), interfaces loopback locales (`127.0.0.1`) o servicios en redes privadas empresariales (RFC 1918 / RFC 4193).

El objetivo de este issue es implementar un componente de seguridad dedicado (`SSRFValidator`) que:
1. Bloquee de forma determinista peticiones a `127.0.0.1`, `169.254.169.254` y redes privadas (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `fc00::/7`).
2. Valide tanto direcciones IP literales como dominios (resolviendo DNS para prevenir bypasses por DNS rebinding).
3. Permita configurar allowlists explícitas de dominios (`SSRF_ALLOWED_HOSTS`) y subredes CIDR (`SSRF_ALLOWED_NETWORKS`), así como el flag `SSRF_ALLOW_PRIVATE_NETWORKS`.
4. Provea un método de escaneo profundo para argumentos generados por el LLM en herramientas de red (`validate_tool_arguments_for_ssrf`).

---

## 2. Reutilización y Adaptación (Código Origen)

- Se tomaron los principios arquitectónicos de defensa por capas estipulados en `informe_arquitectonico_3.md` (Sección 15).
- Se implementó un validador completo basado en la biblioteca estándar `ipaddress` y `socket`, sin introducir dependencias pesadas ni de terceros.
- Se integró la configuración en `app.core.config.Settings`.

---

## 3. Decisiones de Diseño

1. **Catálogo Exhaustivo de Redes Prohibidas (`DEFAULT_BLOCKED_NETWORKS`):**
   - Incorpora no solo loopback (`127.0.0.0/8`, `::1`) y metadatos de nube (`169.254.0.0/16`, `fe80::/10`), sino también rangos de NAT de operador (`100.64.0.0/10`), redes privadas RFC 1918 / RFC 4193, multidifusión (`224.0.0.0/4`, `ff00::/8`) y rangos de documentación/benchmarking (`192.0.2.0/24`, `198.51.100.0/24`, etc.).
2. **Defensa contra DNS Rebinding:**
   - Para cualquier URL con nombre de host que no esté explícitamente en la allowlist, `validate_url` resuelve la dirección vía `socket.getaddrinfo` e inspecciona todas las IPs devueltas (IPv4 e IPv6). Si alguna de ellas pertenece a un rango restringido, la solicitud es rechazada inmediatamente.
3. **Restricción Estricta de Esquemas:**
   - Solo se autorizan esquemas `http` y `https`. Esquemas peligrosos como `file://`, `ftp://`, `gopher://` son rechazados antes de cualquier resolución.
4. **Inspección de Argumentos de Tools (`validate_tool_arguments_for_ssrf`):**
   - Escanea expresiones regulares de URLs e IPs aisladas dentro de los parámetros de texto enviados a tools con `makes_http_requests=True`.

---

## 4. Criterios de Aceptación Verificados

- [x] Peticiones y URLs apuntando a `127.0.0.1` bloqueadas.
- [x] Peticiones y URLs apuntando a `169.254.169.254` (metadata IMDS) bloqueadas.
- [x] Redes privadas (RFC 1918) bloqueadas por defecto.
- [x] Soporte para allowlist de hostnames (`*.cabocom.net`, `api.github.com`) y subredes CIDR explícitas.
- [x] Flag `allow_private_networks=True` permitiendo redes RFC 1918 manteniendo siempre bloqueados loopback y metadata.
- [x] 79 tests pasando en suite completa (100% verde).
