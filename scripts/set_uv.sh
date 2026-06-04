#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)

cd "$PROJECT_ROOT"

export UV_CACHE_DIR="$PROJECT_ROOT/.cache/uv"
export UV_PYTHON_INSTALL_DIR="$PROJECT_ROOT/.cache/uv/python"

if command -v uv >/dev/null 2>&1; then
    UV_CMD="uv"
elif python3 -m uv --version >/dev/null 2>&1; then
    UV_CMD="python3 -m uv"
else
    echo "uv not found. Installing uv with pip..."
    python3 -m pip install --user uv
    UV_CMD="python3 -m uv"
fi

if [ ! -x "$PROJECT_ROOT/.venv/bin/python" ]; then
    echo "Creating virtual environment at .venv..."
    $UV_CMD venv --python "$(command -v python3)"
else
    echo "Using existing virtual environment at .venv"
fi

echo "Installing requirements.txt into .venv..."
$UV_CMD pip install --python "$PROJECT_ROOT/.venv/bin/python" -r "$PROJECT_ROOT/requirements.txt"

mkdir -p "$PROJECT_ROOT/data" "$PROJECT_ROOT/logs"

echo "Environment is ready."
echo "Activate it with: source .venv/bin/activate"
