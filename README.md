# 瞬旅 FlashTrip

AI 驱动、轻量高颜值、可扩展的自研多功能旅行规划应用。

- 前端：Vue 3 + Vite + shadcn-vue (Tailwind CSS v4) + MapLibre GL JS
- 后端：Python 3.12 + FastAPI + SQLAlchemy 2.0 + Alembic
- 数据：默认 SQLite（`/data` 卷），安装向导可切换 PostgreSQL / Redis
- AI：小米 MiMo / 通义千问 / DeepSeek / Kimi / OpenAI / 自定义 OpenAI 兼容端点
- 地图：OpenFreeMap / Mapbox（可选）/ 高德 / 百度 / 天地图，支持无缝切换
- 部署：GitHub Actions 构建单镜像 → GHCR，`docker run` 一条命令启动

> 协议：MIT。参考 [TREK](https://github.com/liketrek/TREK) 的信息架构，未使用其 AGPL 源码，详见 `NOTICE.md`。

## 快速开始（Docker）

```bash
docker run -d --name flashtrip \
  -p 8000:8000 \
  -v flashtrip-data:/data \
  -e TZ=Asia/Shanghai \
  -e FLASHTRIP_LOG_LEVEL=INFO \
  -e FLASHTRIP_SECRET_KEY="<可选；不填则由向导生成并强制提示备份>" \
  --restart unless-stopped \
  ghcr.io/sunny-335/flashtrip:latest
```

> **容器内默认监听 8000**。若对外想用别的端口，有两种写法（二选一，别混用）：
>
> | 目标 | 写法 | 反向代理目标 |
> | --- | --- | --- |
> | 只换宿主机端口（**推荐，无需重建镜像**） | `-p 6781:8000` | `http://127.0.0.1:6781` |
> | 容器内也改成 6781 | `-e FLASHTRIP_PORT=6781 -p 6781:6781` | `http://127.0.0.1:6781` |
>
> 写成 `-p 6781:6781` 却不带 `FLASHTRIP_PORT=6781`，容器内 6781 无人监听 → 反代必然 **502 Bad Gateway**。
> 注意：`FLASHTRIP_PORT` 需镜像内已包含该支持（重建/重新拉取后才生效）；当前 GHCR 镜像请先用第一种写法。

浏览器打开 <http://localhost:8000/> → 自动跳转 `/install` → 六步向导：

1. **数据库**：默认 SQLite（`/data/flashtrip.db`），可切换外部 PostgreSQL 并测试连接
2. **管理员**：账号、邮箱/手机号、密码
3. **AI**：选供应商 → 填 base_url / API Key → 探测 `/models` → 选择模型（可配降级优先级）
4. **地图**：provider / Key / 默认底图 / 审图号（附合规提示）
5. **安全**：主密钥备份、可选 Redis、AI 工具开关
6. **确认**：提交后自动迁移、创建管理员、锁定向导

健康检查：`curl http://localhost:8000/api/v1/health`

## 本地开发

```bash
# 后端
cd backend
python -m pip install uv && uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000

# 前端（另开终端）
cd frontend
pnpm install --allow-build=esbuild --allow-build=vue-demi
pnpm dev            # http://localhost:5173，/api 代理到 8000
```

构建前端产物：`pnpm build` → `frontend/dist/`；生产时由 FastAPI 托管。

## 配置说明

| 位置 | 内容 |
| --- | --- |
| `/data/config.json` | **权威配置**：DB 连接串、安装状态、`secret_key` 等（原子写入 + DB 镜像） |
| DB `app_config` | 配置镜像，config.json 丢失时用于恢复回写 |
| 环境变量 | 统一前缀 `FLASHTRIP_`：`SECRET_KEY` / `PORT` / `DATA_DIR` / `STATIC_DIR` / `DATABASE_URL` / `REDIS_URL` / `LOG_LEVEL` / `TZ` / `VERSION` |
| DB 加密列 | LLM / 地图 API Key 用 Fernet 加密；主密钥存于 `/data/config.json`（或由 `FLASHTRIP_SECRET_KEY` 提供），**丢失后密文不可解，必须备份** |

**向导配置不读取 compose 环境变量**；API Key 只在运行时由用户在向导填写，不进镜像、不进仓库、不进前端。

## 目录

```
backend/    FastAPI 应用、模型、迁移、服务、测试
frontend/   Vue3 SPA
scripts/    entrypoint / 镜像探测 / 本地构建
.github/    CI/CD（GHCR 单镜像）
deploy/     外部 PG/Redis 连接示例
```

## Troubleshooting（已核实坑）

| 现象 | 原因与处理 |
| --- | --- |
| `/api/*` 返回 index.html | 禁止 `app.mount("/", StaticFiles(html=True))`；本项目注册顺序为 API → `/assets` → catch-all，`tests/test_static_routing.py` 常驻回归 |
| 拖拽后顺序弹回 | `v-for` 必须 `:key="item.id"` |
| 切换底图后标记消失 | `setStyle()` 是破坏性的，需相机快照 + overlay registry 重放 |
| SQLite `database is locked` | 单进程 uvicorn + WAL + `busy_timeout=5000`；禁止 `--workers>1` |
| GHCR 推送 403 | workflow 缺 `permissions: packages: write` |
| 重启后向导重来 | 检查 `/data` 卷是否持久化、`config.json` 是否存在 |
| 更换主密钥后 API Key 失效 | 需重新填写密钥；`FLASHTRIP_SECRET_KEY` 必须备份 |
| 反向代理 **502 Bad Gateway** | 容器内默认监听 `8000`；`-p 6781:6781` 不带 `FLASHTRIP_PORT=6781` 时容器内无监听。改成 `-p 6781:8000`，或加 `-e FLASHTRIP_PORT=6781`。用 `docker exec flashtrip curl -fsS http://127.0.0.1:8000/api/v1/health` 先确认容器内服务存活 |
| 反向代理后 AI 对话 / 协作不同步 | SSE 需要 `proxy_buffering off;` + `proxy_read_timeout 300s;` + `proxy_http_version 1.1;` 与 `Upgrade`/`Connection` 头，否则流式响应会被缓冲或超时截断 |

## 状态

按里程碑 M0–M6 实施，详见计划文件。当前为开发阶段。
