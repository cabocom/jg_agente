# ==============================================================================
# Etapa 1: Builder (Compilación e instalación determinista de dependencias)
# ==============================================================================
FROM python:3.12.6-slim AS builder

WORKDIR /build

# Instalar herramientas mínimas de compilación para librerías C/C++ (asyncpg, etc.)
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Argumento opcional para origen de instalación del SDK (GitLab Registry, PyPI, wheel o git URL)
ARG SDK_INSTALL_SOURCE=""

# Copiar manifiesto de dependencias, requirements y README
COPY pyproject.toml requirements.txt* README.md ./

# Instalar dependencias del proyecto en prefijo aislado /install (incluye jg-agente-sdk y CLI jg)
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --prefix=/install "jg-agente-sdk>=1.0.0" && \
    if [ -n "$SDK_INSTALL_SOURCE" ]; then \
        pip install --no-cache-dir --prefix=/install "$SDK_INSTALL_SOURCE"; \
    fi && \
    pip install --no-cache-dir --prefix=/install .

# ==============================================================================
# Etapa 2: Code Preparation & Obfuscation (Cython)
# ==============================================================================
FROM python:3.12.6-slim AS code-obfuscator

WORKDIR /stage

COPY app/ ./app
COPY plugins/ ./plugins
COPY alembic/ ./alembic
COPY alembic.ini ./alembic.ini
COPY docker/compile_cython.py ./compile_cython.py

# Argumento para habilitar compilación Cython durante docker build (por defecto activado en producción)
ARG OBFUSCATE=true

RUN if [ "$OBFUSCATE" = "true" ]; then \
        echo "🔒 [CYTHON] Compilando lógica Python a binarios nativos ELF (.so)..."; \
        apt-get update && \
        apt-get install -y --no-install-recommends gcc libc6-dev && \
        pip install --no-cache-dir cython setuptools && \
        python compile_cython.py app plugins && \
        rm -rf /var/lib/apt/lists/*; \
    else \
        echo "⚡ [CYTHON] Desactivado: empaquetando código estándar..."; \
    fi && \
    rm -f compile_cython.py

# ==============================================================================
# Etapa 3: Runner (Imagen final de producción sin herramientas de compilación)
# ==============================================================================
FROM python:3.12.6-slim AS runner

# Crear usuario y grupo de sistema no-root (UID/GID 10001) para máxima seguridad
RUN groupadd -g 10001 appgroup && \
    useradd -u 10001 -g appgroup -s /sbin/nologin -m appuser

WORKDIR /app

# Copiar paquetes instalados desde la etapa builder (incluye SDK y CLI jg en /usr/local/bin)
COPY --from=builder /install /usr/local

# Copiar código preparado/ofuscado desde la etapa code-obfuscator
COPY --from=code-obfuscator /stage/app ./app
COPY --from=code-obfuscator /stage/plugins ./plugins
COPY --from=code-obfuscator /stage/alembic ./alembic
COPY --from=code-obfuscator /stage/alembic.ini ./alembic.ini

# Permisos para usuario appuser en directorios de trabajo y efímeros
RUN mkdir -p /app/data /tmp && \
    chown -R appuser:appgroup /app /tmp

USER 10001:10001

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    UVICORN_WORKERS=2

EXPOSE 8000

# Comprobación de salud nativa contra endpoint /health
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')" || exit 1

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS:-2}"]
