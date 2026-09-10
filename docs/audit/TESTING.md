# Pruebas

Ejecución observada: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider -q`.

Resultado: 2 fallos, 4 omitidas. Los dos fallos son `plugins/jg_plugin_conversational/tests/test_news_tool.py` (simulación y XML mockeado): `news.py:140` lanza `SSRFValidationError` al no resolver `www.europapress.es`. Se omitieron pruebas de checkpointer/auditoría PostgreSQL porque `localhost:5433` no estaba disponible.

La suite cubre unidades, contratos y nodos, pero no una llamada HTTP no autenticada contra `/executions/*`, firma HMAC válida/inválida/replay, coexistencia de dos agentes en la misma BD, ni flujo Dashboard→agente con servicios reales.
