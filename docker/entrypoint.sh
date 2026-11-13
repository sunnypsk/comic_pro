#!/bin/sh
# PUID/PGID support for NAS deployments (Synology, QNAP, Unraid, TrueNAS).
set -eu

DATA_DIR="${COMICPRO_DATA_DIR:-/data}"
PUID="${PUID:-1000}"
PGID="${PGID:-1000}"
PORT="${PORT:-8080}"
BASE_PATH="${COMICPRO_BASE_PATH:-}"

mkdir -p "$DATA_DIR/db" "$DATA_DIR/library" "$DATA_DIR/cache/pages" "$DATA_DIR/cache/covers" \
    "$DATA_DIR/config/sources"
umask 002

ROOT_ARG=""
if [ -n "$BASE_PATH" ]; then
    ROOT_ARG="--root-path $BASE_PATH"
fi

if [ "$(id -u)" = "0" ]; then
    groupmod -o -g "$PGID" app >/dev/null 2>&1 || true
    usermod -o -u "$PUID" app >/dev/null 2>&1 || true
    chown -R "$PUID:$PGID" "$DATA_DIR" 2>/dev/null || true
    export HOME=/tmp

    if [ "$#" -gt 0 ]; then
        exec gosu "$PUID:$PGID" "$@"
    fi
    # shellcheck disable=SC2086
    exec gosu "$PUID:$PGID" sh -c "exec uvicorn app.main:create_app --factory \
        --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips '*' $ROOT_ARG"
fi

if [ "$#" -gt 0 ]; then
    exec "$@"
fi
# shellcheck disable=SC2086
exec sh -c "exec uvicorn app.main:create_app --factory \
    --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips '*' $ROOT_ARG"
