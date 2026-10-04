# 03. Seguridad, Aislamiento de Red y Sandboxing (`jg_agente`)

[← Volver al README](../README.md) | [← 02. Grafo Cognitivo](02_cognitive_graph.md) | [04. Persistencia →](04_persistence_state.md)

---

## 1. Principio de Mínimo Privilegio y Zero-Trust

`jg_agente` opera bajo el supuesto de que cualquier herramienta de dominio o parámetro recibido puede contener anomalías o vectores de ataque. La ejecución de código se confina a través de tres capas ortogonales:

1. **Capa de Transporte:** Validación criptográfica de firmas HMAC-SHA256 y ventanas anti-replay.
2. **Capa de Control de Acceso e Inyección:** `SecurityGuard` (inspección de argumentos, directory traversal y shell injection).
3. **Capa de Red:** `SSRFValidator` con DNS Pinning y filtrado CIDR determinista.

---

## 2. SecurityGuard (`app/security/guard.py`)

`SecurityGuard` es el singleton thread-safe que evalúa toda operación antes de su ejecución física.

### 2.1 Inspección Universal de Inyecciones
- **Directory Traversal:** Normaliza rutas mediante `os.path.normpath`, `os.path.abspath` y `os.path.realpath`, evaluando rutas absolutas, traversal relativo (`..`) y expansión de home (`~`). Bloquea cualquier acceso a rutas del sistema protegidas (`/etc`, `/boot`, `/root`, `/sys`, `/proc`, `/dev`, `/usr`, `/bin`, `/sbin`, `/lib`, `/var/run`, etc.).
- **Doble Patrón de Shell Injection (Tolerancia de URLs):**
  - **Argumentos Generales:** `SHELL_INJECTION_PATTERN = [;&$`\n\r><|\\'\"]` intercepta concatenadores, pipes y comillas en parámetros estándar.
  - **Parámetros de URL HTTP/HTTPS:** `URL_SHELL_INJECTION_PATTERN = [;`$\n\r><|\\]` permite intencionalmente el carácter `&` (separador legítimo de parámetros query string) y comillas, evitando falsos positivos al invocar APIs remotas.

### 2.2 Invarianza de Seguridad frente a Roles Administrativos (`AGENTE-SEC-06`)
`jg_agente` desacopla estrictamente la identidad del llamador de las restricciones perimetrales:
- La pertenencia a roles privilegiados (`role: admin`) o la posesión de permisos comodín (`*`) **únicamente valida los scopes requeridos por la herramienta** (`required_permissions`).
- **Invariante Absoluto:** Ningún usuario o rol, por elevado que sea su privilegio, puede eludir las validaciones contra inyección de comandos, directory traversal, filtros SSRF o la obligatoriedad de confirmación humana (HITL) para herramientas `HIGH`/`CRITICAL`.

### 2.3 Política de Aprobación Humana (HITL)
- Herramientas con `risk_level` `HIGH` o `CRITICAL` son bloqueadas deterministamente con decisión `REQUIRE_HUMAN_APPROVAL`, a menos que la invocación cuente con `bypass_approval=True` sustentado por `approved_step_ids` o `approved_tool_names` provenientes de una autorización previa.

### 2.4 Ejecución con Timeouts Aislados
Toda invocación a herramientas se envuelve en límites temporales estrictos para evitar el agotamiento de workers:
- **Herramientas síncronas:** Se ejecutan en un worker dedicado de `concurrent.futures.ThreadPoolExecutor(max_workers=1)` bajo `asyncio.wait_for(timeout=tool.timeout_sec)`.
- **Herramientas asíncronas:** Se ejecutan bajo `asyncio.wait_for(coro, timeout=tool.timeout_sec)`.

---

## 3. Prevención de Server-Side Request Forgery (`SSRFValidator`)

Implementado en `app/security/ssrf.py`, mitiga ataques de SSRF y falsificación de DNS mediante validación estricta y **DNS Pinning**.

### 3.1 Rangos de Red Bloqueados por Defecto
El validador bloquea sin excepción:
- **Loopback IPv4/IPv6:** `127.0.0.0/8`, `::1/128`, `0.0.0.0/8`.
- **Link-Local & Cloud Metadata:** `169.254.0.0/16` (bloqueo directo de `169.254.169.254` para AWS, Azure, GCP y OpenStack), `fe80::/10`.
- **Redes Privadas (RFC 1918 / RFC 4193):** `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `fc00::/7` (salvo que `SSRF_ALLOW_PRIVATE_NETWORKS=true` se configure explícitamente).
- **Rangos Especiales y de Test:** `100.64.0.0/10` (CGNAT), `192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24`.
- **Multicast y Reservadas:** `224.0.0.0/4`, `240.0.0.0/4`, `ff00::/8`.
- **Hostnames prohibidos:** `localhost`, `metadata.google.internal`, `metadata`, `instance-data`, y cualquier dominio terminado en `.local`, `.internal` o `.localhost`.

### 3.2 DNS Pinning a Nivel Socket TCP
Para neutralizar ataques de tipo **Time-of-Check to Time-of-Use (TOCTOU)** y **DNS Rebinding**:
1. El validador resuelve el hostname a su dirección IP previa conexión.
2. Si la IP supera el filtrado CIDR, se "fija" (*pinned IP*) en un mapa de transporte.
3. Los transportes personalizados `SSRFSafeSyncBackend` y `SSRFSafeAsyncBackend` (extensiones de `httpcore` y `httpx`) abren el socket TCP directamente hacia la IP fijada, manteniendo intacta la cabecera `Host` original para preservar la negociación TLS/SNI.

---

## 4. Almacenamiento Seguro de Credenciales (POSIX 0600)

El intercambio de tokens y la persistencia del `permanent_secret` generado por el Dashboard se gestiona mediante `CredentialStore` ([app/core/registration.py](../app/core/registration.py)):
- Escritura atómica mediante archivo temporal con `os.replace` y `os.fsync`.
- Permisos de archivo forzados a `0600` (`-rw-------`), restringiendo el acceso exclusivamente al usuario del proceso en el contenedor.

---

## 5. Auditoría Inmutable y Buffer Circular (`SecurityAuditLogger`)

El registrador de auditoría de seguridad ([app/security/audit.py](../app/security/audit.py)) implementa un esquema dual de persistencia:

1. **Persistencia Asíncrona en PostgreSQL:**
   - Cada estímulo, evaluación de política, ejecución de herramienta o decisión HITL se programa en segundo plano mediante `asyncio.create_task` hacia la tabla relacional `core_audit_records`.
   - La inserción es no bloqueante, protegiendo la latencia del ciclo cognitivo principal.

2. **Buffer Circular en Memoria (`AUDIT_LOG_MAX_HISTORY`):**
   - Mantiene simultáneamente una cola `collections.deque(maxlen=settings.AUDIT_LOG_MAX_HISTORY)` (por defecto 1.000 eventos).
   - En caso de indisponibilidad transitoria de la base de datos o fallos de conexión, los registros permanecen accesibles en memoria para telemetría y diagnósticos, garantizando cero pérdida de observabilidad local sin desbordamiento de RAM.

---

## 6. Navegación

- [← Anterior: 02. Grafo Cognitivo y Máquina de Estados](02_cognitive_graph.md)
- [Índice General](../README.md)
- [Siguiente: 04. Persistencia, Estado y Checkpointing →](04_persistence_state.md)
