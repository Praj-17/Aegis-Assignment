#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)

if [ ! -x "$PROJECT_ROOT/.venv/bin/python" ]; then
    echo "Missing .venv. Run ./scripts/set_uv.sh first."
    exit 1
fi

cd "$PROJECT_ROOT"
export PYTHONPATH="$PROJECT_ROOT/src"

exec "$PROJECT_ROOT/.venv/bin/uvicorn" \
    app:app \
    --host "${APP_HOST:-0.0.0.0}" \
    --port "${APP_PORT:-8000}" \
    "$@"
