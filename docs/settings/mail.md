# 邮件（SMTP）

邮件配置位于「设置 → 邮件」（config.json 的 `mail` 段），基于标准库 `smtplib`，零额外依赖。

## 配置字段

| 字段 | 说明 |
| --- | --- |
| `host` | SMTP 服务器地址（如 `smtp.example.com`） |
| `port` | 端口（465 / 587 等） |
| `username` | 登录账号 |
| `password` | 登录口令（保存后加密为 `password_enc`） |
| `use_tls` | 是否使用 SSL/TLS |
| `from_name` | 发件人显示名（默认「瞬旅 FlashTrip」） |
| `from_addr` | 发件地址 |

## 安全要点

- SMTP 口令经 Fernet 加密存储，仅在连接瞬间解密使用。
- 发送失败只记录**异常类型名**——SMTP 异常消息可能回显账号 / 口令，因此不会写入日志。
- 保存后可发送**测试邮件**验证连通性与发件配置。

## 用途

- 出行前天气建议邮件（配合[天气服务](/settings/weather)）。
- 协作邀请等系统通知。

::: tip
安装向导第 5 步可跳过邮件配置，后续在设置页补配即可。
:::
