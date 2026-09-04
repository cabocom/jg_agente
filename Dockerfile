# ==============================================================================
# Etapa 1: Builder (Compilación e instalación determinista de dependencias)
# ==============================================================================
FROM python:3.12-slim AS builder

WORKDIR /build

# Instalar herramientas mínimas de compilación para librerías C/C++ (asyncpg, etc.)
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Copiar manifiesto de dependencias y README
COPY pyproject.toml README.md ./

# Instalar dependencias del proyecto en prefijo aislado /install
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --prefix=/install .

# ==============================================================================
# Etapa 2: Runner (Imagen final limpia sin herramientas de compilación)
# ==============================================================================
FROM python:3.12-slim AS runner

# Crear usuario y grupo de sistema no-root (UID/GID 10001) para máxima seguridad
RUN groupadd -g 10001 appgroup && \
    useradd -u 10001 -g appgroup -s /sbin/nologin -m appuser

WORKDIR /app

# Copiar paquetes instalados desde la etapa builder
COPY --from=builder /install /usr/local

# Copiar código fuente de la aplicación
COPY app/ ./app

# Permisos para usuario appuser en directorios de trabajo y efímeros
RUN mkdir -p /app/data /tmp && \
    chown -R appuser:appgroup /app /tmp

USER 10001:10001

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

EXPOSE 8000

# Comprobación de salud nativa contra endpoint /health
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
