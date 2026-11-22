"""AI 供应商预设：只提供**可覆盖的 base_url**，绝不硬编码模型名。

模型名必须来自运行时 `/models` 探测或用户在向导里手填。
密钥（api_key_enc）只在后端用 decrypt() 解出，不进入任何响应体或日志。
"""
from __future__ import annotations

from typing import Any

import httpx

from app.core.config_store import get_config_store
from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger
from app.core.security import decrypt

log = get_logger(__name__)

PROVIDER_DEFAULTS: dict[str, dict[str, str]] = {
    "deepseek": {"label": "DeepSeek", "base_url": "https://api.deepseek.com"},
    "qwen": {"label": "通义千问 Qwen", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"},
    "kimi": {"label": "Kimi / Moonshot", "base_url": "https://api.moonshot.cn/v1"},
    "mimo": {"label": "MiMo", "base_url": "https://api.xiaomimimo.com/v1"},
    "openai": {"label": "OpenAI", "base_url": "https://api.openai.com/v1"},
    "custom": {"label": "自定义 OpenAI 兼容端点", "base_url": ""},
}


def _cfg(cfg: dict | None) -> dict:
    return cfg if cfg is not None else get_config_store().load()


def _entries(cfg: dict) -> dict[str, dict]:
    """兼容 {'ai': {'providers': {id: {...}}}} 与 list[{id, ...}] 两种向导结构。"""
    raw = (cfg.get("ai") or {}).get("providers")
    if isinstance(raw, dict):
        return {str(k): dict(v) for k, v in raw.items() if isinstance(v, dict)}
    if isinstance(raw, list):
        return {
            str(item["id"]): dict(item)
            for item in raw
            if isinstance(item, dict) and item.get("id")
        }
    return {}


def _has_key(entry: dict) -> bool:
    return bool(entry.get("api_key_enc") or entry.get("key_enc"))


def _decrypt(enc: Any) -> str:
    try:
        return decrypt(str(enc))
    except Exception:  # noqa: BLE001  主密钥变更等情况不得泄露密文
        log.warning("ai.key_decrypt_failed")
        raise AppError(ErrorCode.AI_PROVIDER_ERROR, "AI 密钥无法解密，请在设置中重新填写") from None


def resolve_provider_configs(cfg: dict | None, preferred: str | None = None) -> list[dict[str, Any]]:
    """构建按 priority 排序的可用供应商链；preferred 置顶作为主供应商。

    每项含明文 key（仅内存），模型名取配置中的动态值；缺 key / 缺模型 / 显式
    disabled 的供应商不参与，避免用硬编码模型名兜底。
    """
    cfg = _cfg(cfg)
    entries = _entries(cfg)
    out: list[dict[str, Any]] = []
    ids = list(PROVIDER_DEFAULTS) + [k for k in entries if k not in PROVIDER_DEFAULTS]
    for pid in ids:
        entry = entries.get(pid, {})
        enc = entry.get("api_key_enc") or entry.get("key_enc") or ""
        if not enc or entry.get("enabled") is False:
            continue
        default = PROVIDER_DEFAULTS.get(pid, {})
        base_url = str(entry.get("base_url") or default.get("base_url") or "")
        model = str(entry.get("model") or "")
        if not base_url or not model:
            continue
        out.append(
            {
                "id": pid,
                "label": str(entry.get("label") or default.get("label") or pid),
                "base_url": base_url.rstrip("/"),
                "key": _decrypt(enc),
                "model": model,
                "priority": int(entry.get("priority") or 99),
                "timeout_s": float(entry.get("timeout_s") or 60),
                "cost_per_1k_prompt": entry.get("cost_per_1k_prompt") or 0,
                "cost_per_1k_completion": entry.get("cost_per_1k_completion") or 0,
            }
        )
    out.sort(key=lambda item: item["priority"])
    if preferred:
        out = [c for c in out if c["id"] == preferred] + [c for c in out if c["id"] != preferred]
    return out


def list_ai_providers(cfg: dict | None = None) -> list[dict[str, Any]]:
    """/ai/providers：脱敏列表，仅暴露 hasKey 布尔，不返回任何密文/明文。"""
    cfg = _cfg(cfg)
    entries = _entries(cfg)
    result = []
    ids = list(PROVIDER_DEFAULTS) + [k for k in entries if k not in PROVIDER_DEFAULTS]
    for pid in ids:
        entry = entries.get(pid, {})
        default = PROVIDER_DEFAULTS.get(pid, {})
        result.append(
            {
                "id": pid,
                "label": str(entry.get("label") or default.get("label") or pid),
                "baseUrl": str(entry.get("base_url") or default.get("base_url") or ""),
                "model": str(entry.get("model") or ""),  # 空表示尚未选择，需调 /ai/models
                "enabled": bool(entry.get("enabled", True)),
                "hasKey": _has_key(entry),
                "priority": int(entry.get("priority") or 99),
                "timeoutS": float(entry.get("timeout_s") or 60),
            }
        )
    return result


def list_models(provider: str, base_url: str | None = None, key: str | None = None,
                cfg: dict | None = None) -> list[dict[str, Any]]:
    """动态调用 OpenAI 兼容 /models，禁止硬编码模型名。"""
    cfg = _cfg(cfg)
    entry = _entries(cfg).get(provider, {})
    default = PROVIDER_DEFAULTS.get(provider, {})
    url = str(base_url or entry.get("base_url") or default.get("base_url") or "").rstrip("/")
    if not url:
        raise AppError(ErrorCode.AI_PROVIDER_ERROR, "该供应商尚未配置 base_url")
    if key is None:
        enc = entry.get("api_key_enc") or entry.get("key_enc") or ""
        if not enc:
            raise AppError(ErrorCode.AI_PROVIDER_ERROR, "该供应商尚未配置密钥")
        key = _decrypt(enc)
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(f"{url}/models", headers={"Authorization": f"Bearer {key}"})
        if resp.status_code != 200:
            raise AppError(ErrorCode.AI_PROVIDER_ERROR, "获取模型列表失败，请检查密钥与地址")
        data = resp.json().get("data") or []
        return [
            {"id": str(item.get("id")), "ownedBy": str(item.get("owned_by") or provider)}
            for item in data
            if isinstance(item, dict) and item.get("id")
        ]
    except AppError:
        raise
    except Exception as exc:  # noqa: BLE001  不带密钥/URL 的异常详情
        log.warning("ai.list_models_failed", provider=provider, error_type=type(exc).__name__)
        raise AppError(ErrorCode.AI_PROVIDER_ERROR, "模型列表探测失败，请稍后重试") from None
