#!/bin/sh
# 容器入口：幂等迁移 → 单进程 uvicorn（SQLite 单写者，禁止 --workers > 1）
set -eu

cd /app
mkdir -p "${FLASHTRIP_DATA_DIR:-/data}/uploads" "${FLASHTRIP_DATA_DIR:-/data}/logs"

echo "[flashtrip] running alembic upgrade head ..."
/app/.venv/bin/alembic upgrade head

echo "[flashtrip] starting uvicorn on 0.0.0.0:8000 (single worker)"
exec /app/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
