"""AI 服务包。

子模块按需惰性导入，避免包初始化时连带加载 openai SDK / ORM 依赖：
  - providers.py  预设 base_url（不含模型名）、/models 动态探测、脱敏列表
  - gateway.py    LLMGateway（原生 openai SDK、SSE、重试、降级、停止）
  - tools.py      ToolRegistry（只读白名单 / 写工具二次确认与权限复用）
  - audit.py      ai_audit_logs / ai_messages 落库
"""
