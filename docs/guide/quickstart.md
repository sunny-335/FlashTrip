# 部署与安装

瞬旅 FlashTrip 以单镜像交付：前端构建产物、后端 API 与本文档站全部由同一个 FastAPI 进程托管。默认使用 SQLite，数据落在 `/data` 卷中，无需额外启动数据库容器。

## Docker 运行

```bash
docker run -d --name flashtrip \
  -p 8000:8000 \
  -v flashtrip-data:/data \
  -e TZ=Asia/Shanghai \
  -e FLASHTRIP_SECRET_KEY="<请替换为长期保存的主密钥>" \
  --restart unless-stopped \
  ghcr.io/sunny-335/flashtrip:latest
```

浏览器打开 `http://localhost:8000/` 即自动进入安装向导（见[安装向导](/guide/wizard)）。

健康检查：

```bash
curl http://localhost:8000/api/v1/health
```

::: warning 端口与反向代理
容器默认监听 8000。仅更换宿主机端口用 `-p 6781:8000`；如需容器内一并改端口，加 `-e FLASHTRIP_PORT=6781` 并配合 `-p 6781:6781`。反向代理目标必须与容器内端口一致，否则返回 502。
:::

## Docker Compose

项目根目录提供 `docker-compose.yml`，默认启动单镜像（含文档站）：

```bash
docker compose up -d
```

如需 PostgreSQL + Redis 的完整栈：

```bash
FLASHTRIP_DATABASE_URL="postgresql+psycopg://flashtrip:flashtrip@postgres:5432/flashtrip" \
FLASHTRIP_REDIS_URL="redis://redis:6379/0" \
docker compose --profile full up -d
```

完整栈会额外启动 `postgres`（默认密码 `flashtrip`，可用 `POSTGRES_PASSWORD` 覆盖）与 `redis` 服务，两者带健康检查与独立数据卷。连接串也可写入同目录 `.env` 后直接 `docker compose --profile full up -d`。详见根目录 `docker-compose.yml` 内注释。

## 环境变量

| 变量 | 说明 |
| --- | --- |
| `FLASHTRIP_SECRET_KEY` | 主密钥：加密 LLM / 地图 / 邮件 / 天气密钥，**必须备份且更新时沿用** |
| `FLASHTRIP_PORT` | 容器内监听端口（默认 8000） |
| `FLASHTRIP_DATA_DIR` | 数据目录（默认 `/data`） |
| `FLASHTRIP_STATIC_DIR` | 前端静态目录（默认 `/app/app/static`） |
| `FLASHTRIP_DATABASE_URL` | 覆盖默认 SQLite（优先级高于 config.json） |
| `FLASHTRIP_REDIS_URL` | Redis 连接串 |
| `FLASHTRIP_LOG_LEVEL` | 日志级别（默认 INFO） |
| `TZ` | 时区（默认 Asia/Shanghai） |

::: tip
业务配置的权威来源是 `/data/config.json`，环境变量只承载引导级参数。主密钥丢失后密文不可解，请务必备份。
:::

## 文档站

本站随镜像一同发布，部署后访问 `http://<你的地址>/FlashTrip/` 即可查看，无需额外配置。
