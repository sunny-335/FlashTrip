# syntax=docker/dockerfile:1.7
# 瞬旅 FlashTrip · 前后端 + 文档站单镜像
#   stage 1  frontend : Node 22 构建 Vue3 SPA → dist
#   stage 2  docs     : Node 22 构建 VitePress 文档站（base=/FlashTrip/）→ dist
#   stage 3  runtime  : Python 3.12 (uv) + FastAPI 托管静态文件，单进程 uvicorn
# 镜像源由 scripts/mirror_probe.sh 探测后以 --build-arg 注入，默认 official。

ARG APT_MIRROR=""
ARG PIP_INDEX_URL=""
ARG NPM_REGISTRY=""

# ---------------------------------------------------------------- frontend
FROM node:22-slim AS frontend
ARG NPM_REGISTRY
WORKDIR /web
RUN corepack enable \
 && corepack prepare pnpm@12.18.0 --activate \
 && npm config set fetch-retries 5 \
 && npm config set fetch-timeout 120000 \
 && if [ -n "$NPM_REGISTRY" ]; then npm config set registry "$NPM_REGISTRY"; fi
# 先复制清单以复用依赖缓存层
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile --allow-build=esbuild --allow-build=vue-demi
COPY frontend/ ./
RUN pnpm build \
 && test -f /web/dist/index.html

# ---------------------------------------------------------------- docs (VitePress)
FROM node:22-slim AS docs
ARG NPM_REGISTRY
WORKDIR /docs
RUN corepack enable \
 && corepack prepare pnpm@12.18.0 --activate \
 && npm config set fetch-retries 5 \
 && npm config set fetch-timeout 120000 \
 && if [ -n "$NPM_REGISTRY" ]; then npm config set registry "$NPM_REGISTRY"; fi
COPY docs/package.json docs/pnpm-lock.yaml docs/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile --allow-build=esbuild
COPY docs/ ./
RUN pnpm docs:build \
 && test -f /docs/.vitepress/dist/index.html

# ---------------------------------------------------------------- runtime
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
ARG APT_MIRROR
ARG PIP_INDEX_URL
RUN if [ -n "$APT_MIRROR" ]; then \
      sed -i "s|deb.debian.org|${APT_MIRROR}|g" /etc/apt/sources.list.d/debian.sources 2>/dev/null || true; \
    fi \
 && apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates tzdata \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system flash \
 && useradd --system --gid flash --home-dir /app --shell /usr/sbin/nologin flash \
 && mkdir -p /app/data /data

ENV PIP_DEFAULT_TIMEOUT=60 \
    PIP_RETRIES=5 \
    PIP_INDEX_URL=${PIP_INDEX_URL:-https://pypi.org/simple} \
    UV_INDEX_URL=${PIP_INDEX_URL:-https://pypi.org/simple} \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    FLASHTRIP_PORT=8000 \
    FLASHTRIP_DATA_DIR=/data \
    FLASHTRIP_STATIC_DIR=/app/app/static

WORKDIR /app

COPY backend/pyproject.toml backend/uv.lock ./
# --no-install-project：此时 /app/app 尚未 COPY，避免 hatchling 构建当前项目失败
RUN uv sync --frozen --no-dev --no-install-project

COPY backend/ ./
# 前端构建产物注入：dist 必须在启动时存在，否则 SPA 500
COPY --from=frontend /web/dist ./app/static
# 文档站注入：VitePress 产物挂到 /FlashTrip（挂载见 backend/app/docs_mount.py）
COPY --from=docs /docs/.vitepress/dist ./app/static/docs
ENV PATH="/app/.venv/bin:$PATH"
COPY scripts/entrypoint.sh /entrypoint.sh
RUN chmod 0755 /entrypoint.sh \
 && mkdir -p /data/uploads /data/logs \
 && chown -R flash:flash /app /data

VOLUME ["/data"]
# EXPOSE 仅为元数据，实际监听端口由 FLASHTRIP_PORT 决定（默认 8000）
EXPOSE 8000

# shell form：${FLASHTRIP_PORT} 在容器运行时展开，能读到 docker run -e 的覆盖值
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${FLASHTRIP_PORT}/api/v1/health" >/dev/null || exit 1

# 保持单进程：SQLite 单写者约束，禁止 --workers > 1
ENTRYPOINT ["/entrypoint.sh"]
