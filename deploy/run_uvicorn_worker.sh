#!/bin/sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)"

PROCESS_NUM="${1:-0}"
UVICORN_BASE_PORT="${UVICORN_BASE_PORT:-8001}"
UVICORN_HOST="${UVICORN_HOST:-0.0.0.0}"
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

    if [ -x "${PROJECT_ROOT}/.venv/bin/python" ]; then
        printf '%s\n' "${PROJECT_ROOT}/.venv/bin/python"
        return
    fi

    command -v python
}

PYTHON_BIN="$(resolve_python_bin)"

cd "${PROJECT_ROOT}"
export PYTHONUNBUFFERED=1

exec "${PYTHON_BIN}" -m uvicorn app:app \
    --host "${UVICORN_HOST}" \
    --port "${PORT}" \
    --timeout-keep-alive 120
