#!/bin/sh
set -eu

PROCESS_NUM="${1:-0}"
UVICORN_BASE_PORT="${UVICORN_BASE_PORT:-8001}"
PORT=$((UVICORN_BASE_PORT + PROCESS_NUM))

resolve_python_bin() {
    if [ -n "${UV_PROJECT_ENVIRONMENT:-}" ] && [ -x "${UV_PROJECT_ENVIRONMENT}/bin/python" ]; then
        printf '%s\n' "${UV_PROJECT_ENVIRONMENT}/bin/python"
        return
    fi

    if [ -x "/mnt/.devops_uv_cache/venv/bin/python" ]; then
        printf '%s\n' "/mnt/.devops_uv_cache/venv/bin/python"
        return
    fi

    if [ -x "/app/.venv/bin/python" ]; then
        printf '%s\n' "/app/.venv/bin/python"
        return
    fi

    command -v python
}

PYTHON_BIN="$(resolve_python_bin)"

cd /app
export PYTHONUNBUFFERED=1

exec "${PYTHON_BIN}" -m uvicorn app:app \
    --host 127.0.0.1 \
    --port "${PORT}" \
    --timeout-keep-alive 120
