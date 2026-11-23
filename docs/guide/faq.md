# 常见问题

## 部署与访问

### 反向代理返回 502？

容器内端口与映射 / 反代目标不一致。用以下命令确认容器内实际监听端口：

```bash
docker exec flashtrip curl -fsS http://127.0.0.1:8000/api/v1/health
```

如使用了 `FLASHTRIP_PORT` 修改容器内端口，反向代理目标必须同步修改。

### 访问 `/api/*` 返回了前端页面？

静态托管注册顺序必须为 API → `/assets` → catch-all。官方镜像已内置正确顺序；若自行构建，请勿改为 `app.mount("/", StaticFiles(html=True))`。

### SSE 流式输出中断？

反向代理需要：

```nginx
proxy_buffering off;
proxy_read_timeout 300s;
proxy_http_version 1.1;
```

### 重启后安装向导又出现了？

确认 `/data` 卷存在且持久化、`config.json` 未丢失：

```bash
docker volume inspect flashtrip-data
docker exec flashtrip ls -la /data
```

## 数据与迁移

### SQLite 报 `database is locked`？

容器保持单进程 uvicorn（SQLite 单写者约束），禁止 `--workers > 1`。默认启用 WAL。仍频繁出现时建议切换 PostgreSQL（compose 完整栈）。

### 切换底图后标记消失了？

`setStyle()` 是破坏性操作，覆盖层需要重放；刷新页面即可恢复。

### 如何从 SQLite 切换到 PostgreSQL？

在「安装向导 → 数据库」（未安装时）或设置页填写 PostgreSQL 连接串并完成迁移；连接串示例：`postgresql+psycopg://flashtrip:<密码>@postgres:5432/flashtrip`。

## 密钥与安全

### 主密钥丢了怎么办？

`FLASHTRIP_SECRET_KEY`（或 config.json 的 `secret_key`）丢失后，已加密的 LLM / 地图 / 邮件 / 天气密钥**无法解密**，只能在各设置页重新填写。这就是为什么必须备份主密钥。

### API Key 会不会进镜像或仓库？

不会。API Key 只在安装向导或设置页填写，经 Fernet 加密后存入 `/data/config.json`，不进镜像、不进仓库、不进日志（日志仅记录异常类型名）。

## 文档站

### 文档站地址是什么？

部署后访问 `http://<你的地址>/FlashTrip/`（注意结尾斜杠；不带斜杠会自动重定向）。文档站随主镜像一起发布，无需单独部署。
