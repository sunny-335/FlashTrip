#!/bin/sh
# 容器入口：幂等迁移 → 单进程 uvicorn（SQLite 单写者，禁止 --workers > 1）
set -eu

cd /app
mkdir -p "${FLASHTRIP_DATA_DIR:-/data}/uploads" "${FLASHTRIP_DATA_DIR:-/data}/logs"

echo "[flashtrip] running alembic upgrade head ..."
/app/.venv/bin/alembic upgrade head

# 容器内监听端口可用 FLASHTRIP_PORT 覆盖（默认 8000）。
# 修改后必须同步调整 -p 映射与反向代理的目标端口，否则会出现 502。
PORT="${FLASHTRIP_PORT:-8000}"
case "$PORT" in
  ''|*[!0-9]*) echo "[flashtrip] FLASHTRIP_PORT 必须是数字，当前值: '$PORT'" >&2; exit 1 ;;
esac

echo "[flashtrip] starting uvicorn on 0.0.0.0:${PORT} (single worker)"
exec /app/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --workers 1
