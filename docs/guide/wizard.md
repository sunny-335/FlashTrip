# 安装向导

首次访问 `http://localhost:8000/` 会自动进入七步安装向导，全部完成后向导锁定，后续配置在「设置」页调整。

## 七个步骤

1. **数据库**：选择默认 SQLite（零配置，落 `/data` 卷），或填写外部 PostgreSQL 连接串（含连接测试）。使用 compose 完整栈时，应用已通过 `FLASHTRIP_DATABASE_URL` 预先指定，向导会带出该连接串，地址形如 `postgresql+psycopg://flashtrip:<密码>@postgres:5432/flashtrip`。
2. **管理员**：设置管理员账号与密码，带实时强度校验。
3. **人工智能**：选择供应商（MiMo / 通义千问 / DeepSeek / Kimi / OpenAI / 自定义 OpenAI 兼容端点），填写 API Key 并可探测可用模型。
4. **地图**：选择供应商与默认底图。OpenFreeMap 无需密钥即可使用；高德 / 天地图 / Mapbox 的密钥填写见[地图 Provider 配置](/settings/map)。
5. **邮件通知**：可跳过，后续在设置页补配 SMTP（见[邮件设置](/settings/mail)）。
6. **安全备份**：备份主密钥提示，可选配置 Redis，确认 AI 工具开关。
7. **确认安装**：自动执行数据库迁移、创建管理员、锁定安装向导。

## 配置存放在哪里

| 位置 | 内容 |
| --- | --- |
| `/data/config.json` | 权威配置：数据库连接、安装状态、`secret_key` 等（原子写入 + DB 镜像） |
| 数据库 `app_config` 表 | 配置镜像，config.json 丢失时用于恢复 |
| 环境变量 | 仅引导级参数，见[部署与安装](/guide/quickstart) |

::: warning
LLM / 地图 / 邮件 / 天气的密钥均以 Fernet 加密落盘，主密钥来自 config.json 的 `secret_key` 或环境变量 `FLASHTRIP_SECRET_KEY`。API Key 只在向导或设置页填写，不进镜像、不进仓库。
:::
