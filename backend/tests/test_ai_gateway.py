"""AI 网关：密钥加密/解密、模型名不硬编码、跨供应商降级、全部失败明确 2004、工具开关、
done 携带 conversationId、文本形式工具调用拦截、stream_options 兼容降级。

全部用 monkeypatch / 假 SDK 客户端，绝不发起真实网络请求。
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.core.errors import AppError, ErrorCode
from app.core.security import decrypt, encrypt
from app.services.ai import gateway, providers
from app.services.ai.gateway import LLMGateway
from app.services.ai.text_tool_calls import ACTION_DELTA, TextToolCallParser


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


def _parse_events(raw: str) -> list[tuple[str, dict]]:
    """把 SSE 文本解析为 (事件名, data) 列表。"""
    events: list[tuple[str, dict]] = []
    for block in raw.split("\n\n"):
        name = None
        data = None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[len("event: "):]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
        if name is not None:
            events.append((name, data))
    return events


def _delta_text(raw: str) -> str:
    return "".join(data.get("delta") or "" for name, data in _parse_events(raw) if name == "delta")


def _collect(parser: TextToolCallParser, pieces: list[str]) -> list[tuple[str, object]]:
    out: list[tuple[str, object]] = []
    for piece in pieces:
        out.extend(parser.feed(piece))
    out.extend(parser.flush())
    return out


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


# ---------------------------------------------------------------- 新增：done 事件协议
def test_done_event_carries_conversation_id():
    cfg = _cfg(main_key=encrypt("sk-main"))
    raw = "".join(LLMGateway(
        cfg=cfg, client_factory=lambda *a: _FakeClient(chunks=_chunks("你好"))
    ).chat([{"role": "user", "content": "hi"}], stream=True, conversation_id="conv-42"))
    done = [data for name, data in _parse_events(raw) if name == "done"]
    assert done and done[0]["conversationId"] == "conv-42"
    assert done[0]["content"] == "你好"


def test_stopped_done_event_also_carries_conversation_id():
    cfg = _cfg(main_key=encrypt("sk-main"))
    gateway.stop("conv-stop-1")
    raw = "".join(LLMGateway(
        cfg=cfg, client_factory=lambda *a: _FakeClient(chunks=_chunks("你好"))
    ).chat([{"role": "user", "content": "hi"}], stream=True, conversation_id="conv-stop-1"))
    done = [data for name, data in _parse_events(raw) if name == "done"]
    assert done and done[0]["stopped"] is True
    assert done[0]["conversationId"] == "conv-stop-1"


# ---------------------------------------------------------------- 新增：文本形式工具调用拦截
def test_text_tool_call_single_chunk_intercepted():
    """单块到达的裸 JSON 工具调用被拦截：不进 delta，转为结构化调用。"""
    cfg = _cfg(main_key=encrypt("sk-main"))
    text = '好的，我来查天气。\n{"name": "get_weather", "arguments": {"city": "北京"}}\n查询完成。'
    collected: list[dict] = []
    raw = "".join(LLMGateway(
        cfg=cfg, client_factory=lambda *a: _FakeClient(chunks=[_delta_chunk(text), _usage_chunk()])
    ).chat([{"role": "user", "content": "hi"}], stream=True,
           conversation_id="conv-1", tool_calls_out=collected))
    deltas = _delta_text(raw)
    assert '{"name"' not in deltas
    assert deltas.startswith("好的，我来查天气。")
    assert deltas.endswith("查询完成。")
    assert collected == [{"id": "call_text_0", "name": "get_weather",
                          "arguments": '{"city": "北京"}'}]
    done = [data for name, data in _parse_events(raw) if name == "done"][0]
    assert done["conversationId"] == "conv-1"
    assert done["tool_calls"][0]["name"] == "get_weather"
    assert '{"name"' not in done["content"]


def test_text_tool_call_split_across_chunks_intercepted():
    """跨 chunk 切断的裸 JSON 工具调用同样被拦截（缓冲 + 回溯补发）。"""
    cfg = _cfg(main_key=encrypt("sk-main"))
    pieces = ["好的\n{\"na", "me\": \"get_weat", "her\", \"argu", "ments\": {\"city\"", ": \"北京\"}}"]
    collected: list[dict] = []
    raw = "".join(LLMGateway(
        cfg=cfg, client_factory=lambda *a: _FakeClient(
            chunks=[_delta_chunk(p) for p in pieces] + [_usage_chunk()])
    ).chat([{"role": "user", "content": "hi"}], stream=True, tool_calls_out=collected))
    assert _delta_text(raw) == "好的\n"
    assert collected == [{"id": "call_text_0", "name": "get_weather",
                          "arguments": '{"city": "北京"}'}]


def test_text_tool_call_in_json_fence_intercepted():
    """```json 代码块形态的工具调用整块吞掉，不再漏给用户。"""
    cfg = _cfg(main_key=encrypt("sk-main"))
    text = '```json\n{"name": "get_weather", "arguments": {"city": "北京"}}\n```'
    collected: list[dict] = []
    raw = "".join(LLMGateway(
        cfg=cfg, client_factory=lambda *a: _FakeClient(chunks=[_delta_chunk(text), _usage_chunk()])
    ).chat([{"role": "user", "content": "hi"}], stream=True, tool_calls_out=collected))
    assert _delta_text(raw) == ""
    assert collected and collected[0]["name"] == "get_weather"


def test_text_tool_call_in_tag_and_to_functions_forms_intercepted():
    """特殊标记（[tool_call]）与伪协议（to=functions.x）形态都能拦截。"""
    parser = TextToolCallParser()
    actions = _collect(parser, ['[tool_call]{"name": "get_plan", "arguments": {"trip_id": "t1"}}[/tool_call]'])
    assert [a for a, _ in actions] == ["tool_call"]
    assert actions[0][1]["name"] == "get_plan"

    parser2 = TextToolCallParser()
    actions2 = _collect(parser2, ['to=functions.get_weather\n{"city": "北京"}'])
    assert [a for a, _ in actions2] == ["tool_call"]
    assert actions2[0][1]["name"] == "get_weather"
    assert json.loads(actions2[0][1]["arguments"]) == {"city": "北京"}


def test_batch_text_tool_calls_parsed():
    """{"tool_calls": [...]} 批量形态一次解析出多个调用。"""
    parser = TextToolCallParser()
    text = '{"tool_calls": [{"name": "get_plan", "arguments": {"trip_id": "t1"}},' \
           '{"name": "get_weather", "arguments": {"city": "北京"}}]}'
    actions = _collect(parser, [text])
    calls = [data for action, data in actions if action == "tool_call"]
    assert len(calls) == 2
    assert {c["name"] for c in calls} == {"get_plan", "get_weather"}


def test_normal_prose_not_swallowed():
    """普通正文不被误吃：行内 JSON、非工具的示例代码块原样放行。"""
    cfg = _cfg(main_key=encrypt("sk-main"))
    pieces = [
        "这是一份示例数据：\n",
        "```json\n",
        '{"city": "北京", "days": 3}\n',
        "```\n",
        '注意 {"name": "张三"} 只是行内 JSON，保持原样。',
    ]
    collected: list[dict] = []
    raw = "".join(LLMGateway(
        cfg=cfg, client_factory=lambda *a: _FakeClient(
            chunks=[_delta_chunk(p) for p in pieces] + [_usage_chunk()])
    ).chat([{"role": "user", "content": "hi"}], stream=True, tool_calls_out=collected))
    assert _delta_text(raw) == "".join(pieces)
    assert collected == []


def test_line_start_plain_json_object_passes_through():
    """行首的普通 JSON 对象（无工具形状）不是工具调用，必须原样放行。"""
    parser = TextToolCallParser()
    actions = _collect(parser, ['预算明细：\n{"total": 3000, "currency": "CNY"}\n以上。'])
    deltas = "".join(data for action, data in actions if action == ACTION_DELTA)
    assert deltas == '预算明细：\n{"total": 3000, "currency": "CNY"}\n以上。'
    assert all(action == ACTION_DELTA for action, _ in actions)


def test_unterminated_tool_json_flushed_as_text():
    """流结束仍未闭合的候选按正文放行（宁可漏判不可误吃）。"""
    parser = TextToolCallParser()
    actions = _collect(parser, ['看这段 {"name": "未闭合'])
    deltas = "".join(data for action, data in actions if action == ACTION_DELTA)
    assert deltas == '看这段 {"name": "未闭合'
    assert not any(action == "tool_call" for action, _ in actions)


# ---------------------------------------------------------------- 新增：stream_options 兼容降级
class _UnsupportedStreamOptions(Exception):
    status_code = 400

    def __str__(self) -> str:
        return "Error code: 400 - Unrecognized request argument supplied: stream_options"


class _DowngradeClient:
    """第一次带 stream_options 的请求 400；fail_without_options 时去掉后仍持续故障。"""

    def __init__(self, chunks, fail_without_options: bool = False) -> None:
        self._chunks = list(chunks)
        self._fail_without = fail_without_options
        self.calls: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if "stream_options" in kwargs:
            raise _UnsupportedStreamOptions()
        if self._fail_without:
            raise RuntimeError("upstream unavailable")
        return iter(self._chunks)


def test_stream_options_unsupported_downgrades_and_retries():
    cfg = _cfg(main_key=encrypt("sk-main"))
    client = _DowngradeClient(_chunks("正常回答"))
    raw = "".join(LLMGateway(cfg=cfg, client_factory=lambda *a: client).chat(
        [{"role": "user", "content": "hi"}], stream=True))
    assert "event: delta" in raw and "event: done" in raw
    assert _delta_text(raw) == "正常回答"
    # 只重试一次，且重试时不再携带 stream_options
    assert len(client.calls) == 2
    assert "stream_options" in client.calls[0]
    assert "stream_options" not in client.calls[1]


def test_stream_options_downgrade_reused_within_request(monkeypatch):
    """同一请求内记住降级结论：主供应商后续重试不再反复试错，备用供应商直连成功。"""
    monkeypatch.setattr(gateway.time, "sleep", lambda *_: None)
    cfg = _cfg(main_key=encrypt("sk-main"), backup_key=encrypt("sk-backup"))
    clients: list[_DowngradeClient] = []

    def factory(base_url, key, timeout):
        # 主供应商降级后仍持续故障，验证后续重试不再带 stream_options；备用供应商直接成功
        is_main = "deepseek" in base_url
        client = _DowngradeClient([] if is_main else _chunks("备用回答"),
                                  fail_without_options=is_main)
        clients.append(client)
        return client

    events = "".join(LLMGateway(cfg=cfg, client_factory=factory).chat(
        [{"role": "user", "content": "hi"}]))
    assert "event: done" in events
    assert "备用回答" in events
    # 每次重试都会新建客户端：第 1 次尝试先带 stream_options 400，降级后去掉重试 1 次
    assert len(clients[0].calls) == 2
    assert "stream_options" in clients[0].calls[0]
    assert "stream_options" not in clients[0].calls[1]
    # 第 2、3 次重试记住供应商级结论：一开始就不带 stream_options
    assert all(c.calls[0].get("stream_options") is None for c in clients[1:3])
    assert all(len(c.calls) == 1 for c in clients[1:3])


def test_auth_error_is_not_treated_as_stream_options_issue(monkeypatch):
    """401 鉴权错误不得触发 stream_options 降级，走正常重试与报错。"""

    class _AuthError(Exception):
        status_code = 401

        def __str__(self) -> str:
            return "Error code: 401 - Invalid API key"

    class _AuthClient:
        def __init__(self) -> None:
            self.calls = 0
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

        def _create(self, **kwargs):
            self.calls += 1
            raise _AuthError()

    monkeypatch.setattr(gateway.time, "sleep", lambda *_: None)
    cfg = _cfg(main_key=encrypt("sk-main"))
    client = _AuthClient()
    raw = "".join(LLMGateway(cfg=cfg, client_factory=lambda *a: client).chat(
        [{"role": "user", "content": "hi"}], stream=True))
    assert "event: error" in raw
    assert client.calls == 3  # 每次都带 stream_options，绝不因鉴权错误降级


# ---------------------------------------------------------------- 新增：工具开关语义修正
def test_read_tools_available_by_default_write_gated():
    """向导默认安装形态（security.ai_tools_enabled=False）：只读工具可用，写工具关闭。"""
    from app.services.ai.tools import ToolRegistry

    cfg = {"ai": {}, "security": {"ai_tools_enabled": False}}
    registry = ToolRegistry(cfg=cfg)
    names = {d["function"]["name"] for d in registry.definitions()}
    assert "get_weather" in names
    assert "list_trips" in names
    assert "add_plan_item" not in names
    assert "create_booking" not in names
    with pytest.raises(AppError) as exc:
        registry.execute("add_plan_item", {"title": "x"}, confirmed=True)
    assert exc.value.code == ErrorCode.AI_TOOLS_DISABLED


def test_write_tools_enabled_by_wizard_switch():
    from app.services.ai.tools import ToolRegistry

    cfg = {"security": {"ai_tools_enabled": True}}
    names = {d["function"]["name"] for d in ToolRegistry(cfg=cfg).definitions()}
    assert "add_plan_item" in names
    assert "get_weather" in names
    config = ToolRegistry.config(cfg)
    assert config["enabled"] is True
    assert config["writeEnabled"] is True


def test_master_switch_still_kills_everything():
    from app.services.ai.tools import ToolRegistry

    cfg = {"ai": {"tools_enabled": False}, "security": {"ai_tools_enabled": True}}
    registry = ToolRegistry(cfg=cfg)
    assert registry.definitions() == []
    assert ToolRegistry.config(cfg)["writeEnabled"] is False
