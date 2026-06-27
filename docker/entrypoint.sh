#!/bin/sh
set -e

# CogniForge (Loop Engineering reference) — container entrypoint

if [ -n "${REDIS_URL}" ]; then
  host="$(printf '%s' "$REDIS_URL" | sed -n 's#redis://\([^:/?]*\).*#\1#p')"
  port="$(printf '%s' "$REDIS_URL" | sed -n 's#redis://[^:]*:\([0-9]*\).*#\1#p')"
  host="${host:-redis}"
  port="${port:-6379}"
  echo "[entrypoint] waiting for Redis at ${host}:${port} ..."
  i=0
  while [ "$i" -lt 60 ]; do
    if python - <<'PY' 2>/dev/null
import os, socket
from urllib.parse import urlparse
u = urlparse(os.environ.get("REDIS_URL", "redis://redis:6379/0"))
host = u.hostname or "redis"
port = u.port or 6379
s = socket.socket()
s.settimeout(2)
s.connect((host, port))
s.close()
PY
    then
      echo "[entrypoint] Redis is ready."
      break
    fi
    i=$((i + 1))
    sleep 1
  done
  if [ "$i" -ge 60 ]; then
    echo "[entrypoint] WARNING: Redis not reachable; graph will fall back to MemorySaver."
  fi
fi

for arg in "$@"; do
  if [ "$arg" = "--urls" ]; then
    echo "[entrypoint] using CLI args: $*"
    exec python -m src.main "$@"
  fi
done

# LOOP_* (preferred) with legacy LEARN_LOOP_* fallback
_urls="$(printf '%s' "${LOOP_URLS:-${LEARN_LOOP_URLS:-}}" | tr ',' ' ' | xargs)"
if [ -z "$_urls" ]; then
  echo "[entrypoint] ERROR: --urls is required." >&2
  echo "  Set LOOP_URLS in .env, or pass --urls on the command line." >&2
  echo "  Example: docker compose run --rm cogniforge --urls https://example.com --task-id demo" >&2
  exit 1
fi

set -- --urls
for url in $_urls; do
  set -- "$@" "$url"
done

_goal="${LOOP_GOAL:-${LEARN_LOOP_GOAL:-Master the core knowledge from the provided pages}}"
if [ -n "$_goal" ]; then
  set -- "$@" --goal "$_goal"
fi

_task_id="${LOOP_TASK_ID:-${LEARN_LOOP_TASK_ID:-cogniforge-default}}"
if [ -n "$_task_id" ]; then
  set -- "$@" --task-id "$_task_id"
fi

_thread="${LOOP_THREAD_ID:-${LEARN_LOOP_THREAD_ID:-}}"
if [ -n "$_thread" ]; then
  set -- "$@" --thread-id "$_thread"
fi

echo "[entrypoint] python -m src.main $*"
exec python -m src.main "$@"
