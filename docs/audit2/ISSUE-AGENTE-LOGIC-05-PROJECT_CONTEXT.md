# Contexto del Proyecto: [AGENTE-LOGIC-05] Saturación de Cuota TPM (HTTP 429) por Salidas Masivas de Herramientas y Ausencia de Reintentos

## Descripción del Entorno
- **Componente:** `jg_agente` (Execution Plane)
- **Proveedor LLM:** Groq (`openai/gpt-oss-120b`) / OpenAI-compatible
- **Incidencia:** Error `429 Too Many Requests` durante la ejecución de flujos reflexivos multiturno en el agente DevOps tras invocar la herramienta `docker_logs`.

## Contexto Operativo
Durante la ejecución de tareas operativas como *"hazme un resumen del estado del servidor mirando bien los logs de los contenedores"*, el motor de ejecución autónomo `jg_agente` coordina un grafo LangGraph de múltiples transiciones reflexivas (`reason -> plan -> execute -> evaluate -> reason`).

Al consultar registros de contenedores con `docker_logs`, la salida de texto inyectada en el historial de mensajes elevó abruptamente el recuento de tokens por petición a más de 5.000 tokens. Groq impone una ventana de límite por minuto rodante (TPM - Tokens Per Minute) de 8.000 tokens en sus planes estándar. Al disparar la iteración consecutiva en `evaluate_node`, Groq retornaba inmediatamente un código HTTP `429 Too Many Requests` con la cabecera `x-ratelimit-reset-tokens: 2.5s`.

Debido a que el cliente HTTP `OpenAICompatibleChatModel` ejecutaba `resp.raise_for_status()` inmediatamente sin pausas ni reintentos, el grafo abortaba de forma prematura dejando hilos de ejecución fallidos y la consola web bloqueada en estado de espera.
