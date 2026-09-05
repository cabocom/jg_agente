# Análisis Técnico - ISSUE-F09-T03: Implementación de NewsTool en jg_plugin_conversational

## 1. Alcance y Arquitectura de la Solución
El agente conversacional requiere proveer al modelo titularidad y actualidad informativa sobre temas de interés (tecnología, economía, actualidad general) de forma estructurada y con garantías de seguridad de nivel de infraestructura crítica.

### 1.1 Modelo de Datos (`NewsArgs`)
- `topic`: `str` con longitud máxima de 50 caracteres y validación regex `^[a-zA-Z0-9áéíóúÁÉÍÓÚñÑüÜ\s\-_.,]+$`. Evita la inyección de caracteres de escape o comandos en búsquedas.
- `limit`: `int` acotado entre 1 y 10 (por defecto 5) para limitar el consumo de contexto del LLM y evitar desbordes de memoria.

### 1.2 Ejecución de Consulta (`get_news_fn`)
1. **Validación SSRF:**
   - La URL del feed (por defecto feed oficial de Europa Press Portada) es verificada mediante `SSRFValidator.validate_url()`.
   - Si la URL se resuelve a rangos privados o link-local (`169.254.0.0/16`), se lanza `SSRFValidationError` y la herramienta responde con error seguro.
2. **Llamada HTTP con Timeout:**
   - Ejecución de `httpx.get(feed_url, timeout=5.0, headers={"User-Agent": "jg-agente/0.1.0"})`.
   - Captura y manejo resiliente de `httpx.TimeoutException` y `httpx.RequestError`.
3. **Parseo XML Seguro:**
   - Se parsea el árbol XML de RSS 2.0 buscando `<item>` hijos de `<channel>`.
   - Se extraen `<title>`, `<description>` y `<link>`, filtrando por el término `topic` solicitado.
   - Sanitización de entidades y limpieza de fragmentos CDATA.
4. **Fallback Determinista:**
   - Si no hay conectividad o se fuerza el modo offline, se generan noticias sintéticas deterministas y temáticas (tecnología, economía, nacional) que permiten probar el flujo conversacional sin dependencia de servidores externos.
5. **Contrato `AgentTool`:**
   - Nombre: `get_news`
   - Categoría: `news`
   - `read_only`: `True`
   - `risk_level`: `RiskLevel.LOW`
   - `idempotent`: `True`
   - `makes_http_requests`: `True`

## 2. Prevención de Importes Circulares
Se identificó que importar `SSRFValidator` en el nivel superior del módulo de un plugin podía provocar ciclos de importación con `app.security` -> `audit` -> `db.models`. Para garantizar un acoplamiento limpio y diferido, la importación se realiza de forma perezosa dentro de la función ejecutora `get_news_fn`.
