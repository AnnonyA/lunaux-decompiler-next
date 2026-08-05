#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
HOST="${LUNAUX_HOST:-127.0.0.1}"
PORT="${LUNAUX_PORT:-8000}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "Python 3.11 or newer was not found." >&2
    echo "Install Python, then run this script again." >&2
    exit 1
fi

"$PYTHON_BIN" - <<'PY'
import sys

if sys.version_info < (3, 11):
    raise SystemExit(
        f"Python 3.11 or newer is required; found {sys.version.split()[0]}"
    )
PY

if [ ! -x ".venv/bin/python" ]; then
    echo "Creating virtual environment..."
    "$PYTHON_BIN" -m venv .venv
fi

VENV_PYTHON=".venv/bin/python"

echo "Installing or updating LunaUX Next..."
"$VENV_PYTHON" -m pip install --upgrade pip
"$VENV_PYTHON" -m pip install -e .

echo
echo "Starting LunaUX Next at http://${HOST}:${PORT}"
echo "API documentation: http://${HOST}:${PORT}/docs"
echo "Press Ctrl+C to stop the server."
echo

exec "$VENV_PYTHON" -m lunaux run --host "$HOST" --port "$PORT" "$@"
