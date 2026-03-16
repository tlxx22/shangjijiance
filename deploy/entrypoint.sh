#!/bin/sh
set -eu

SERVER_MODE="${SERVER_MODE:-nginx_uvicorn}"
WORKERS="${WORKERS:-5}"
UVICORN_BASE_PORT="${UVICORN_BASE_PORT:-8001}"
STARTUP_NOTIFY_BIND="${STARTUP_NOTIFY_BIND:-0.0.0.0:80}"
STARTUP_NOTIFY_PID="$$"

export SERVER_MODE WORKERS UVICORN_BASE_PORT STARTUP_NOTIFY_BIND STARTUP_NOTIFY_PID

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

resolve_gunicorn_bin() {
    if [ -n "${UV_PROJECT_ENVIRONMENT:-}" ] && [ -x "${UV_PROJECT_ENVIRONMENT}/bin/gunicorn" ]; then
        printf '%s\n' "${UV_PROJECT_ENVIRONMENT}/bin/gunicorn"
        return
    fi

    if [ -x "/mnt/.devops_uv_cache/venv/bin/gunicorn" ]; then
        printf '%s\n' "/mnt/.devops_uv_cache/venv/bin/gunicorn"
        return
    fi

    if [ -x "/app/.venv/bin/gunicorn" ]; then
        printf '%s\n' "/app/.venv/bin/gunicorn"
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

generate_nginx_upstream_file() {
    : > /tmp/nginx_upstream_servers.conf

    i=0
    while [ "${i}" -lt "${WORKERS}" ]; do
        port=$((UVICORN_BASE_PORT + i))
        printf 'server 127.0.0.1:%s;\n' "${port}" >> /tmp/nginx_upstream_servers.conf
        i=$((i + 1))
    done
}

send_startup_notify_once() {
    PYTHON_BIN="$(resolve_python_bin)"
    "${PYTHON_BIN}" - <<'PY'
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
}

cd /app
repair_playwright_browser_links
send_startup_notify_once

case "${SERVER_MODE}" in
    nginx_uvicorn)
        generate_nginx_upstream_file
        exec supervisord -n -c /app/deploy/supervisord.conf
        ;;
    legacy_gunicorn)
        GUNICORN_BIN="$(resolve_gunicorn_bin)"
        exec "${GUNICORN_BIN}" -c /app/gunicorn.conf.py app:app
        ;;
    *)
        echo "Unsupported SERVER_MODE: ${SERVER_MODE}" >&2
        exit 1
        ;;
esac
