# Contexto del Proyecto: [AGENTE-INFRA-01] Ausencia de Workers en Uvicorn y Versión Menor no Fijada en Dockerfile

## Descripción del Entorno
- **Componente:** `jg_agente` (Infraestructura de Contenerización y Ejecución)
- **Capa Afectada:** Empaquetado Docker y configuración del servidor web ASGI (`Dockerfile`, `app/core/config.py`, `docker-compose.yml`)
- **Severidad:** 🟢 BAJO

## Contexto Operativo
`jg_agente` se despliega como contenedor Docker autónomo tanto en entornos de desarrollo local como en producción mediante orquestación con Docker Compose.
El contenedor expone una API REST construida sobre FastAPI y servida mediante el servidor ASGI Uvicorn en el puerto 8000.
El archivo `Dockerfile` adopta un esquema Multi-Stage Build con dos etapas:
1. `builder`: Compila e instala librerías en un directorio temporal `/install`.
2. `runner`: Imagen limpia final que ejecuta bajo el usuario sin privilegios `appuser` (UID 10001).

## Problema Detectado
1. **Falta de Fijación de Versión Menor en Imagen Base:**
   Tanto en la etapa `builder` como en `runner`, se utilizaba la etiqueta flotante `FROM python:3.12-slim`. Esta directiva resolvía dinámicamente cualquier versión menor o parche liberado por el equipo oficial de Python (3.12.7, 3.12.8, etc.), lo que introducía indeterminismo en la cadena de suministro, riesgo de incompatibilidades sutiles o fallos de compilación inesperados entre compilaciones locales y de CI/CD.
2. **Subutilización de Concurrencia en Uvicorn:**
   El comando `CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]` ejecutaba Uvicorn con un único worker (`workers=1`). Aunque FastAPI es asíncrono, un único proceso de Python queda atado al GIL (Global Interpreter Lock), limitando severamente el throughput ante tareas intensivas de CPU (serialización/deserialización masiva de JSON, cálculo de firmas HMAC o hashing criptográfico).
3. **Falta de Parametrización:**
   No existía ninguna variable de entorno para ajustar el número de workers según los núcleos disponibles en el host o los límites asignados al contenedor.
