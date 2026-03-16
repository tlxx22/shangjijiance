#!/bin/sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)"

SERVER_MODE="${SERVER_MODE:-uvicorn_only}"
WORKERS="${WORKERS:-5}"
UVICORN_BASE_PORT="${UVICORN_BASE_PORT:-8001}"
STARTUP_NOTIFY_BIND="${STARTUP_NOTIFY_BIND:-}"
STARTUP_NOTIFY_PID="$$"

export PROJECT_ROOT SERVER_MODE WORKERS UVICORN_BASE_PORT STARTUP_NOTIFY_BIND STARTUP_NOTIFY_PID

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

resolve_gunicorn_bin() {
    if [ -n "${UV_PROJECT_ENVIRONMENT:-}" ] && [ -x "${UV_PROJECT_ENVIRONMENT}/bin/gunicorn" ]; then
        printf '%s\n' "${UV_PROJECT_ENVIRONMENT}/bin/gunicorn"
        return
    fi

    if [ -x "/mnt/.devops_uv_cache/venv/bin/gunicorn" ]; then
        printf '%s\n' "/mnt/.devops_uv_cache/venv/bin/gunicorn"
        return
    fi

    if [ -x "${PROJECT_ROOT}/.venv/bin/gunicorn" ]; then
        printf '%s\n' "${PROJECT_ROOT}/.venv/bin/gunicorn"
        return
    fi

    command -v gunicorn
}

repair_playwright_browser_links() {
    if [ -d "/mnt/.devops_uv_cache/venv/browsers" ]; then
        mkdir -p /root/.cache/ms-playwright
        ln -sf /mnt/.devops_uv_cache/venv/browsers/* /root/.cache/ms-playwright/ 2>/dev/null || true
    fi

    for d in /root/.cache/ms-playwright/chromium-*/; do
        [ -d "${d}" ] || continue
        if [ -d "${d}chrome-linux64" ]; then
            ln -sf "${d}chrome-linux64" "${d}chrome-linux" 2>/dev/null || true
        fi
    done
}

require_positive_integer() {
    name="$1"
    value="$2"

    case "${value}" in
        ''|*[!0-9]*)
            echo "[entrypoint] ${name} must be a positive integer, got: ${value}" >&2
            exit 1
            ;;
    esac

    if [ "${value}" -lt 1 ]; then
        echo "[entrypoint] ${name} must be >= 1, got: ${value}" >&2
        exit 1
    fi
}

require_valid_port_range() {
    last_port=$((UVICORN_BASE_PORT + WORKERS - 1))
    if [ "${UVICORN_BASE_PORT}" -gt 65535 ] || [ "${last_port}" -gt 65535 ]; then
        echo "[entrypoint] UVICORN_BASE_PORT + WORKERS - 1 must be <= 65535, got: ${last_port}" >&2
        exit 1
    fi
}

resolve_server_mode() {
    case "${SERVER_MODE}" in
        uvicorn_only|legacy_gunicorn)
            ;;
        nginx_uvicorn)
            echo "[entrypoint] SERVER_MODE=nginx_uvicorn is deprecated, using uvicorn_only" >&2
            SERVER_MODE="uvicorn_only"
            ;;
        *)
            echo "Unsupported SERVER_MODE: ${SERVER_MODE}" >&2
            exit 1
            ;;
    esac

    export SERVER_MODE
}

default_startup_notify_bind() {
    case "${SERVER_MODE}" in
        uvicorn_only)
            last_port=$((UVICORN_BASE_PORT + WORKERS - 1))
            if [ "${WORKERS}" -eq 1 ]; then
                printf '127.0.0.1:%s\n' "${UVICORN_BASE_PORT}"
            else
                printf '127.0.0.1:%s~127.0.0.1:%s\n' "${UVICORN_BASE_PORT}" "${last_port}"
            fi
            ;;
        legacy_gunicorn)
            printf '0.0.0.0:80\n'
            ;;
    esac
}

set_startup_notify_bind() {
    if [ -n "${STARTUP_NOTIFY_BIND}" ]; then
        return
    fi

    STARTUP_NOTIFY_BIND="$(default_startup_notify_bind)"
    export STARTUP_NOTIFY_BIND
}

send_startup_notify_once() {
    PYTHON_BIN="$(resolve_python_bin 2>/dev/null || true)"
    if [ -z "${PYTHON_BIN:-}" ]; then
        echo "[entrypoint] startup notify skipped: python not found" >&2
        return 0
    fi

    if ! "${PYTHON_BIN}" - <<'PY'
import os
from src.official_startup_notify import notify_startup_async

notify_startup_async(
    server_meta={
        "pid": os.getenv("STARTUP_NOTIFY_PID", ""),
        "bind": os.getenv("STARTUP_NOTIFY_BIND", "0.0.0.0:80"),
        "workers": os.getenv("WORKERS", ""),
    },
    timeout_s=3.0,
    async_send=False,
)
PY
    then
        echo "[entrypoint] startup notify skipped: hook execution failed" >&2
    fi
}

run_legacy_gunicorn() {
    GUNICORN_BIN="$(resolve_gunicorn_bin)"
    cd "${PROJECT_ROOT}"
    exec "${GUNICORN_BIN}" -c "${PROJECT_ROOT}/gunicorn.conf.py" app:app
}

run_uvicorn_only() {
    PYTHON_BIN="$(resolve_python_bin)"
    cd "${PROJECT_ROOT}"
    exec "${PYTHON_BIN}" "${PROJECT_ROOT}/deploy/run_multi_uvicorn.py"
}

cd "${PROJECT_ROOT}"
resolve_server_mode
require_positive_integer "WORKERS" "${WORKERS}"
if [ "${SERVER_MODE}" = "uvicorn_only" ]; then
    require_positive_integer "UVICORN_BASE_PORT" "${UVICORN_BASE_PORT}"
    require_valid_port_range
fi
set_startup_notify_bind
repair_playwright_browser_links
send_startup_notify_once

case "${SERVER_MODE}" in
    uvicorn_only)
        run_uvicorn_only
        ;;
    legacy_gunicorn)
        run_legacy_gunicorn
        ;;
esac
