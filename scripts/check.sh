#!/usr/bin/env bash
set -e

# Directorio base del proyecto
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

# Determinar ejecutable de entorno virtual si existe
VENV_BIN="$PROJECT_ROOT/.venv/bin"
if [ -d "$VENV_BIN" ]; then
    RUFF="$VENV_BIN/ruff"
    MYPY="$VENV_BIN/mypy"
    PYTEST="$VENV_BIN/pytest"
else
    RUFF="ruff"
    MYPY="mypy"
    PYTEST="pytest"
fi

echo "========================================"
echo "🔍 Ejecutando verificación de código..."
echo "========================================"

echo ""
echo "1️⃣  [Ruff] Análisis de formato y linter..."
"$RUFF" check app tests
"$RUFF" format --check app tests

echo ""
echo "2️⃣  [MyPy] Chequeo estático de tipos estricto..."
"$MYPY" app tests

echo ""
echo "3️⃣  [Pytest] Ejecución de suite de tests..."
"$PYTEST" tests

echo ""
echo "========================================"
echo "✅ ¡Todas las comprobaciones pasaron con éxito!"
echo "========================================"
