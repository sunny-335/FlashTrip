"""AI 网关：密钥加密/解密、模型名不硬编码、跨供应商降级、全部失败明确 2004、工具开关。

全部用 monkeypatch / 假 SDK 客户端，绝不发起真实网络请求。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.errors import AppError, ErrorCode
from app.core.security import decrypt, encrypt
from app.services.ai import gateway, providers
from app.services.ai.gateway import LLMGateway


class _FakeClient:
    def __init__(self, chunks=None, fail=False) -> None:
        self._chunks = list(chunks or [])
        self._fail = fail
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        if self._fail:
            raise RuntimeError("upstream unavailable")
        return iter(self._chunks)


def _delta_chunk(text, tool_calls=None):
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=text, tool_calls=tool_calls))],
        usage=None,
    )


def _usage_chunk(prompt=12, completion=7):
    return SimpleNamespace(choices=[], usage=SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion))


def _chunks(*texts):
    return [_delta_chunk(t) for t in texts] + [_usage_chunk()]


def _cfg(*, main_key: str, backup_key: str | None = None,
         main_model="deepseek-chat", backup_model="qwen-plus") -> dict:
    entries = {
        "deepseek": {
            "api_key_enc": main_key,
            "base_url": "https://api.deepseek.com",
            "model": main_model,
            "priority": 1,
            "enabled": True,
        }
    }
    if backup_key:
        entries["qwen"] = {
            "api_key_enc": backup_key,
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "model": backup_model,
            "priority": 2,
            "enabled": True,
        }
    return {"ai": {"providers": entries}}


def test_key_is_encrypted_and_plain_never_stored_or_leaked():
    plain = "sk-test-main-key-123"
    enc = encrypt(plain)
    assert enc.startswith("ENC:")
    assert plain not in enc
    assert decrypt(enc) == plain
    # 配置里只有密文，明文不出现在序列化结果中
    cfg = _cfg(main_key=enc)
    assert plain not in str(cfg)


def test_gateway_passes_decrypted_key_to_sdk():
    plain = "sk-test-main-key-123"
    cfg = _cfg(main_key=encrypt(plain))
    seen = []

    def factory(base_url, key, timeout):
        seen.append({"base_url": base_url, "key": key, "timeout": timeout})
        return _FakeClient(chunks=_chunks("你好", "世界"))

    events = "".join(LLMGateway(cfg=cfg, client_factory=factory).chat(
        [{"role": "user", "content": "hi"}], stream=True
    ))
    assert "event: delta" in events
    assert "event: done" in events
    assert seen[0]["key"] == plain
    assert seen[0]["timeout"] == 60.0
    assert '"provider": "deepseek"' in events
    assert '"model": "deepseek-chat"' in events


def test_provider_defaults_have_no_model_name():
    for definition in providers.PROVIDER_DEFAULTS.values():
        assert "model" not in definition
        assert "models" not in definition
    assert providers.PROVIDER_DEFAULTS["deepseek"]["base_url"] == "https://api.deepseek.com"
    assert providers.PROVIDER_DEFAULTS["qwen"]["base_url"].endswith("compatible-mode/v1")


def test_provider_without_model_is_skipped_not_fabricated():
    """没选模型就不参与调用，绝不用硬编码模型名兜底。"""
    cfg = {"ai": {"providers": {"deepseek": {
        "api_key_enc": encrypt("sk"), "base_url": "https://api.deepseek.com",
    }}}}
    assert providers.resolve_provider_configs(cfg) == []


def test_list_models_is_dynamic(monkeypatch):
    class _Resp:
        status_code = 200

        def json(self):
            return {"data": [{"id": "my-dynamic-model-v2", "owned_by": "vendor"}]}

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, headers=None):
            assert url == "https://example.test/v1/models"
            assert headers["Authorization"] == "Bearer sk-probe"
            return _Resp()

    monkeypatch.setattr(providers.httpx, "Client", _Client)
    models = providers.list_models("deepseek", base_url="https://example.test/v1", key="sk-probe")
    assert models == [{"id": "my-dynamic-model-v2", "ownedBy": "vendor"}]


def test_fallback_to_backup_provider_is_not_silent(monkeypatch):
    monkeypatch.setattr(gateway.time, "sleep", lambda *_: None)
    cfg = _cfg(main_key=encrypt("sk-main"), backup_key=encrypt("sk-backup"))
    calls = []

    def factory(base_url, key, timeout):
        calls.append(base_url)
        if "deepseek" in base_url:
            return _FakeClient(fail=True)  # 主供应商持续故障
        return _FakeClient(chunks=_chunks("备用回答"))

    events = "".join(LLMGateway(cfg=cfg, client_factory=factory).chat(
        [{"role": "user", "content": "hi"}]
    ))
    assert "event: delta" in events and "event: done" in events
    assert "备用回答" in events
    assert "正在按优先级切换" in events  # 降级不静默
    assert '"provider": "qwen"' in events
    assert '"model": "qwen-plus"' in events  # 降级时用备用供应商自身的动态模型
    assert len(calls) >= 4  # 主 3 次指数退避重试 + 备用 1 次


def test_all_providers_fail_reports_2004(monkeypatch):
    monkeypatch.setattr(gateway.time, "sleep", lambda *_: None)
    cfg = _cfg(main_key=encrypt("sk-main"))
    events = "".join(LLMGateway(
        cfg=cfg, client_factory=lambda *args: _FakeClient(fail=True)
    ).chat([{"role": "user", "content": "hi"}]))
    assert "event: error" in events
    assert '"code": 2004' in events
    assert "AI 供应商调用失败" in events


def test_no_provider_config_raises_before_stream():
    gateway_instance = LLMGateway(cfg={"ai": {"providers": {}}}, client_factory=lambda *a: None)
    with pytest.raises(AppError) as exc:
        gateway_instance.chat([{"role": "user", "content": "hi"}])
    assert exc.value.code == ErrorCode.AI_PROVIDER_ERROR


def test_tools_disabled_returns_2005():
    from app.services.ai.tools import ToolRegistry

    registry = ToolRegistry(cfg={"ai": {"tools_enabled": False}})
    with pytest.raises(AppError) as exc:
        registry.execute("list_trips")
    assert exc.value.code == ErrorCode.AI_TOOLS_DISABLED
    assert registry.definitions() == []


def test_write_tool_requires_frontend_confirmation():
    from app.services.ai.tools import ToolRegistry

    registry = ToolRegistry(cfg={"ai": {"tools_enabled": True}})
    result = registry.execute("create_booking", {"type": "hotel"})
    assert result["needConfirm"] is True
    assert result["permission"] == "booking:write"
