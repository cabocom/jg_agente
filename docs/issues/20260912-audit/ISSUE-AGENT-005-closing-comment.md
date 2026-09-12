### Resolución de [ISSUE-AGENT-005] Fallback offline y resolución de tests en NewsTool (GitLab #46)

Se ha completado la resolución del issue AGENT-005 garantizando el desacoplamiento de DNS en entornos offline para `NewsTool` sin degradar la seguridad SSRF:

1. **Discriminación de Errores de Red vs Infracción SSRF:**
   - Si la validación de la URL RSS de Europa Press no supera la comprobación por indisponibilidad del servidor DNS (`gaierror`, `"resolución dns"`), la herramienta emite un log de advertencia y deriva de inmediato al generador de noticias simuladas deterministas (`_get_simulated_news`).
   - Las violaciones efectivas de la política SSRF (destinos privados, loopback, metadatos en nube) siguen elevando estrictamente `SSRFValidationError`.

2. **Aislamiento en Tests Unitarios:**
   - Se ajustó `test_news_xml_parsing_mocked_http` con mock de resolución DNS a IP pública autorizada.
   - Se añadieron tests dedicados para verificar la conmutación a simulación ante fallo DNS (`test_news_offline_dns_failure_fallback`) y el rechazo ante violaciones reales SSRF (`test_news_real_ssrf_violation_raises`).

3. **Verificación y Calidad:**
   - La suite completa de `jg_agente` pasa al 100% de forma determinista y sin requerir conexión a internet (`scripts/check.sh` conforme en Ruff, MyPy estricto y Pytest).

/close
