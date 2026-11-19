#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
if [ -x "$ROOT_DIR/.venv/bin/python" ]; then
  PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
fi

if [ -d "$ROOT_DIR/frontend/dist" ]; then
  export QINGJIAO_STATIC_DIR="$ROOT_DIR/frontend/dist"
fi

export PYTHONPATH="$ROOT_DIR/backend${PYTHONPATH:+:$PYTHONPATH}"
export MODELSCOPE_CACHE="${MODELSCOPE_CACHE:-$ROOT_DIR/.model_cache/modelscope}"
export QINGJIAO_DATA_DIR="${QINGJIAO_DATA_DIR:-$ROOT_DIR/data}"

echo "Starting Qingjiao Redact Community at http://127.0.0.1:8000"
exec "$PYTHON_BIN" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
