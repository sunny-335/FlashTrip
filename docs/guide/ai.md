# AI 助手

全局悬浮的 AI 助手贯穿整个应用，基于 OpenAI 兼容协议对接多家供应商。

## 支持的供应商

| 供应商 | 默认端点 |
| --- | --- |
| MiMo（小米） | `https://api.xiaomimimo.com/v1` |
| 通义千问 Qwen | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| DeepSeek | `https://api.deepseek.com` |
| Kimi / Moonshot | `https://api.moonshot.cn/v1` |
| OpenAI | `https://api.openai.com/v1` |
| 自定义 | 任意 OpenAI 兼容端点 |

安装向导中填写 API Key 后可自动探测可用模型；密钥经 Fernet 加密落盘。

## 工具与安全边界

AI 助手通过内置工具操作行程数据，安全边界如下：

- **只读工具**（查询行程、日程、费用等）直接调用，无需确认。
- **写操作**（新建 / 修改 / 移动行程数据）需要用户**二次确认**才会执行。
- **删除行程**必须通过「是 / 否」明确确认，防止误删。
- 所有 AI 调用记录审计日志，密钥与审计分离存储。

## 流式输出

对话采用 SSE 流式输出。若部署在反向代理之后，请确认代理配置了 `proxy_buffering off;` 与 `proxy_read_timeout 300s;`，否则可能出现流式中断。
