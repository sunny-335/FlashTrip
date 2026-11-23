# 瞬旅 FlashTrip

AI 驱动的自研多功能旅行规划应用。单镜像部署，首次访问通过安装向导完成配置。

## 技术栈

| 层 | 选型 |
| --- | --- |
| 前端 | Vue 3 + Vite + TypeScript + Tailwind CSS v4 + MapLibre GL JS + PWA |
| 后端 | Python 3.12 + FastAPI + SQLAlchemy 2.0 + Alembic |
| 数据 | SQLite 默认（`/data` 卷），向导可切换 PostgreSQL / Redis |
| AI | 小米 MiMo / 通义千问 / DeepSeek / Kimi / OpenAI / 自定义 OpenAI 兼容端点 |
| 地图 | 高德 / 天地图，预设元数据自动带出署名与审图号；路线与导航支持高德、腾讯、百度导航深链 |
| 文档 | VitePress，应用内路由 `/FlashTrip/` |
| 部署 | GitHub Actions → GHCR 单镜像，支持 `docker run` 与 Docker Compose |

协议：MIT。信息架构参考 [TREK](https://github.com/liketrek/TREK)，未使用其 AGPL 源码，见 `NOTICE.md`。

## 快速开始

```bash
docker run -d --name flashtrip \
  -p 8000:8000 \
  -v flashtrip-data:/data \
  -e TZ=Asia/Shanghai \
  -e FLASHTRIP_SECRET_KEY="<请替换为长期保存的主密钥>" \
  --restart unless-stopped \
  ghcr.io/sunny-335/flashtrip:latest
```

浏览器打开 `http://localhost:8000/`，自动进入七步安装向导：

1. **数据库**：SQLite 或外部 PostgreSQL，带连接测试
2. **管理员**：账号与密码，实时强度校验
3. **人工智能**：供应商、密钥、模型探测
4. **地图**：供应商、密钥、默认底图
5. **邮件通知**：可跳过，后续在设置页补配
6. **安全备份**：主密钥备份、可选 Redis、AI 工具开关
7. **确认安装**：自动迁移、创建管理员、锁定向导

健康检查：`curl http://localhost:8000/api/v1/health`

> 容器默认监听 8000。仅更换宿主机端口用 `-p 6781:8000`；如需容器内一并改端口，加 `-e FLASHTRIP_PORT=6781` 并配合 `-p 6781:6781`。反向代理目标须与容器内端口一致，否则返回 502。

## 更新

镜像发布后，任选一种方式更新。数据保存在 `flashtrip-data` 卷中，不会随容器删除丢失；**必须沿用首次部署的 `FLASHTRIP_SECRET_KEY`**，否则已加密的 API Key 无法解密。

一键脚本（自动继承旧容器的环境变量、端口、卷与重启策略，启动失败自动回滚）：

```bash
sh scripts/update.sh
```

单行命令（不依赖仓库，参数按实际部署调整）：

```bash
docker pull ghcr.io/sunny-335/flashtrip:latest && docker rm -f flashtrip && docker run -d --name flashtrip -p 8000:8000 -v flashtrip-data:/data -e TZ=Asia/Shanghai -e FLASHTRIP_SECRET_KEY="<与首次部署一致>" --restart unless-stopped ghcr.io/sunny-335/flashtrip:latest
```

使用 compose：

```bash
docker compose pull && docker compose up -d --force-recreate
```

更新后确认：`docker exec flashtrip curl -fsS http://127.0.0.1:8000/api/v1/health`

## 功能

- **行程**：每日时间线三栏拖拽、地点/交通卡片、开始/时长/结束联动、冲突标红与 AI 重排、自动保存与快捷键
- **预算与家庭**：总预算及分类预算、家庭成员与儿童标记、常用出行人员和多人费用分摊
- **地图与路线**：高德/天地图底图、POI 与地理编码、路线规划；地图地点可选择高德/腾讯/百度导航
- **天气邮件**：天气与建议先预览，手动发送或按出发前设置提醒；支持旅行中每日天气邮件
- **对象存储**：本地、阿里云 OSS、Amazon S3 兼容存储可选
- **业务**：预定、交通、费用（多人/儿童/家庭智能分账）、物品清单、瞬间（图片上传、逐条对外可见性）
- **视图**：仪表盘、足迹地图、行程记忆、协作成员与细粒度权限、邀请链接（首次设密 / 强制改密）
- **AI**：全局悬浮助手，只读工具直用、写操作二次确认、删除行程需「是/否」确认；出行前天气建议邮件
- **分享**：公开只读链接，可含交通、酒店、物品、可选费用与公开瞬间
- **其他**：PWA 离线、深浅色/跟随系统主题、手机/平板/PC 三端、备份导入导出与定时备份、PDF/ICS 导出

## 本地开发

```bash
cd backend
python -m pip install uv && uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000

cd frontend
pnpm install --allow-build=esbuild --allow-build=vue-demi
pnpm dev
```

前端产物由 `pnpm build` 生成到 `frontend/dist/`，生产时由 FastAPI 托管。

## 配置

| 位置 | 内容 |
| --- | --- |
| `/data/config.json` | 权威配置：数据库连接、安装状态、`secret_key` 等（原子写入 + DB 镜像） |
| DB `app_config` | 配置镜像，config.json 丢失时用于恢复 |
| 环境变量 | `FLASHTRIP_` 前缀：`SECRET_KEY` / `PORT` / `DATA_DIR` / `STATIC_DIR` / `DATABASE_URL` / `REDIS_URL` / `LOG_LEVEL` / `TZ` / `VERSION` |
| 加密列 | LLM / 地图 / 邮件 / 天气密钥用 Fernet 加密，主密钥存于 config.json 或 `FLASHTRIP_SECRET_KEY` |

主密钥丢失后密文不可解，必须备份。API Key 只在向导或设置页填写，不进镜像、不进仓库。

## 目录

```
backend/    FastAPI 应用、模型、迁移、服务、测试
frontend/   Vue 3 SPA
scripts/    容器入口、镜像探测、本地构建与更新脚本
.github/    CI/CD（GHCR 单镜像）
deploy/     外部 PostgreSQL / Redis 连接示例
```

## 运维要点

| 现象 | 处理 |
| --- | --- |
| 反向代理 502 | 容器内端口与映射/反代目标不一致；用 `docker exec flashtrip curl -fsS http://127.0.0.1:8000/api/v1/health` 确认 |
| SSE 流式中断 | 反代需 `proxy_buffering off;`、`proxy_read_timeout 300s;`、`proxy_http_version 1.1;` |
| `/api/*` 返回 index.html | 静态托管注册顺序必须为 API → `/assets` → catch-all |
| SQLite `database is locked` | 单进程 uvicorn + WAL；禁止 `--workers>1` |
| 切换底图后标记消失 | `setStyle()` 为破坏性操作，需相机快照与 overlay 重放 |
| 重启后向导重来 | 确认 `/data` 卷持久化且 `config.json` 存在 |
