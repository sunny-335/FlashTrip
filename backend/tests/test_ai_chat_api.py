"""AI 对话 API 集成测试：SSE 多轮工具循环、标题生成、会话管理端点、历史结构化。

全部通过 monkeypatch 假网关/假注册表与内存 SQLite 运行，绝不发起真实网络请求。
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1 import ai as ai_module
from app.api.v1 import deps
from app.core.errors import ErrorCode
from app.db.base import Base
from app.models.ai import AiAuditLog, AiConversation, AiMessage
from app.services.ai.gateway import sse

_TABLES = [AiConversation.__table__, AiMessage.__table__, AiAuditLog.__table__]

_PROVIDER = {
    "id": "deepseek", "label": "DeepSeek", "base_url": "https://api.deepseek.com",
    "key": "sk-fake", "model": "deepseek-chat", "priority": 1, "timeout_s": 60.0,
    "cost_per_1k_prompt": 0, "cost_per_1k_completion": 0,
}


class _ScriptedGateway:
    """脚本化假网关：无工具结果时产出 get_weather 调用，回灌后给最终回答。

    stream=False 视为标题生成请求，返回短标题；fail_title=True 时抛异常验证回退。
    round1_calls 可定制第一轮产出的工具调用（去重/未知工具用例）。
    """

    instances: list[_ScriptedGateway] = []

    def __init__(self, cfg=None, db=None, client_factory=None, *, round1_calls=None,
                 fail_title: bool = False, title: str = "北京天气查询") -> None:
        self.calls: list[dict] = []
        self.round1_calls = round1_calls or [{"id": "", "name": "get_weather",
                                              "arguments": '{"city": "北京"}'}]
        self.fail_title = fail_title
        self.title = title
        _ScriptedGateway.instances.append(self)

    def chat(self, messages, provider=None, model=None, stream=True, *,
             user_id=None, trip_id=None, conversation_id=None,
             tools=None, tool_calls_out=None):
        self.calls.append({
            "messages": [dict(m) for m in messages],
            "tools": tools, "provider": provider, "model": model, "stream": stream,
        })
        if not stream:
            # 标题生成：一条非流式短请求
            if self.fail_title:
                raise RuntimeError("upstream unavailable")
            yield sse("delta", {"delta": self.title})
            yield sse("done", {"content": self.title, "provider": "deepseek", "model": "deepseek-chat"})
            return
        if any(m.get("role") == "tool" for m in messages):
            # 工具结果已回灌：第二轮输出最终回答
            yield sse("delta", {"delta": "北京今天晴，适合出行。"})
            yield sse("done", {
                "provider": "deepseek", "model": "deepseek-chat",
                "content": "北京今天晴，适合出行。", "tool_calls": [],
                "conversationId": conversation_id,
            })
            return
        # 第一轮：正文 + 工具调用
        yield sse("delta", {"delta": "我先查一下天气。"})
        if tool_calls_out is not None:
            tool_calls_out.extend(self.round1_calls)
        yield sse("done", {
            "provider": "deepseek", "model": "deepseek-chat",
            "content": "我先查一下天气。", "tool_calls": list(self.round1_calls),
        })


class _FakeRegistry:
    """假工具注册表：只记录执行，返回固定结果。"""

    instances: list[_FakeRegistry] = []

    def __init__(self, cfg=None, db=None, user=None, trip_id=None) -> None:
        self.executed: list[tuple[str, dict]] = []
        _FakeRegistry.instances.append(self)

    @staticmethod
    def definitions() -> list[dict]:
        return [{"type": "function", "function": {"name": "get_weather", "parameters": {}}}]

    def execute(self, name, arguments=None, *, confirmed=False) -> dict:
        self.executed.append((name, dict(arguments or {})))
        return {"tool": name, "result": {"city": (arguments or {}).get("city"), "weather": "晴"}}


def _parse_events(raw: str) -> list[tuple[str, dict]]:
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


@pytest.fixture()
def env(client, monkeypatch):
    """内存 SQLite + 已登录 owner + 假网关/假注册表，跑 /ai/chat 全链路。"""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=_TABLES)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = Session()

    fake_user = SimpleNamespace(id="owner-1", role="owner", must_set_password=False)
    monkeypatch.setitem(client.app.dependency_overrides, deps.require_user, lambda: fake_user)
    monkeypatch.setitem(client.app.dependency_overrides, deps.get_db, lambda: db)

    # 标题任务改为同步执行、标题落库改为记录器，便于确定性断言
    title_updates: list[tuple[str, str]] = []
    title_failures: list[str] = []
    monkeypatch.setattr(ai_module, "_spawn_title_task", lambda task: task())
    monkeypatch.setattr(ai_module, "_update_conversation_title",
                        lambda conv_id, user_id, title, expect=None: title_updates.append((conv_id, title)) or True)
    monkeypatch.setattr(ai_module, "_record_title_failure",
                        lambda conv_id, user_id: title_failures.append(conv_id))

    yield SimpleNamespace(
        client=client, db=db, monkeypatch=monkeypatch, user=fake_user,
        title_updates=title_updates, title_failures=title_failures,
    )
    db.close()
    engine.dispose()


def _patch_gateway(monkeypatch, gateway_cls=None, registry_cls=None) -> None:
    monkeypatch.setattr(ai_module, "resolve_provider_configs", lambda cfg, preferred=None: [dict(_PROVIDER)])
    monkeypatch.setattr(ai_module, "LLMGateway", gateway_cls or _ScriptedGateway)
    monkeypatch.setattr(ai_module, "ToolRegistry", registry_cls or _FakeRegistry)
    _ScriptedGateway.instances.clear()
    _FakeRegistry.instances.clear()


def _chat(env, body: dict):
    return env.client.post("/api/v1/ai/chat", json=body)


def test_chat_multi_round_tool_loop_with_tools_every_round(env):
    """多轮工具循环：system prompt 注入、每轮都带 tools、done 带 conversationId。"""
    _patch_gateway(env.monkeypatch)
    resp = _chat(env, {"messages": [{"role": "user", "content": "北京天气怎么样？"}],
                       "provider": "deepseek", "model": "deepseek-chat"})
    assert resp.status_code == 200
    events = _parse_events(resp.text)

    gateway = _ScriptedGateway.instances[0]
    # 每一轮请求都以 system prompt 开头，且始终携带 tools
    rounds = [c for c in gateway.calls if c["stream"]]
    assert len(rounds) == 2
    for call in rounds:
        assert call["messages"][0]["role"] == "system"
        assert "FlashTrip" in call["messages"][0]["content"]
        assert call["tools"], "每一轮工具循环都必须携带 tools"
        assert call["provider"] == "deepseek" and call["model"] == "deepseek-chat"
    # 第二轮回灌了第一轮的 assistant 工具调用与 tool 结果
    round2 = rounds[1]["messages"]
    assert any(m.get("role") == "assistant" and m.get("tool_calls") for m in round2)
    tool_msgs = [m for m in round2 if m.get("role") == "tool"]
    assert len(tool_msgs) == 1 and tool_msgs[0]["tool_call_id"]

    # SSE 事件：tool_call → tool_result → 最终 delta → done（带 conversationId）
    names = [name for name, _ in events]
    assert "tool_call" in names and "tool_result" in names
    done = [data for name, data in events if name == "done"][-1]
    assert done["conversationId"]
    conv = env.db.get(AiConversation, done["conversationId"])
    assert conv is not None
    deltas = "".join(d.get("delta") or "" for n, d in events if n == "delta")
    assert "我先查一下天气。" in deltas and "北京今天晴，适合出行。" in deltas
    tool_call = [d for n, d in events if n == "tool_call"][0]
    assert tool_call["name"] == "get_weather"
    assert tool_call["needConfirm"] is False
    # 工具结果已按结构化落库（role=tool），供历史还原
    tool_rows = env.db.query(AiMessage).filter(AiMessage.role == "tool").all()
    assert len(tool_rows) == 1 and tool_rows[0].tool_call_id


def test_chat_title_generated_after_first_round(env):
    """首轮完成后异步生成标题：先截断回退，再被低成本短请求结果覆盖。"""
    _patch_gateway(env.monkeypatch)
    resp = _chat(env, {"messages": [{"role": "user", "content": "北京天气怎么样？"}]})
    assert resp.status_code == 200
    # 截断回退标题（首条用户消息前 16 字符）
    assert env.title_updates[0][1] == "北京天气怎么样？"
    # 网关可用：被同一模型的非流式短请求结果覆盖（≤12 字）
    assert env.title_updates[1][1] == "北京天气查询"
    assert env.title_failures == []
    gateway = _ScriptedGateway.instances[0]
    title_call = [c for c in gateway.calls if not c["stream"]]
    assert len(title_call) == 1
    assert title_call[0]["tools"] is None  # 标题请求不带工具


def test_chat_title_falls_back_silently_when_gateway_fails(env):
    """标题生成失败：静默回退截断标题，只落审计（2015），绝不影响对话流。"""

    class _FailTitleGateway(_ScriptedGateway):
        def __init__(self, *args, **kwargs):
            kwargs["fail_title"] = True
            super().__init__(*args, **kwargs)

    _patch_gateway(env.monkeypatch, gateway_cls=_FailTitleGateway)
    resp = _chat(env, {"messages": [{"role": "user", "content": "帮我规划五天的东京行程"}]})
    assert resp.status_code == 200
    assert "event: error" not in resp.text
    # 只有一次截断回退，无第二次覆盖；失败仅记录
    assert len(env.title_updates) == 1
    assert env.title_updates[0][1] == "帮我规划五天的东京行程"
    assert len(env.title_failures) == 1


def test_chat_duplicate_tool_calls_deduplicated(env):
    """同一轮内相同工具 + 相同参数的重复调用只执行一次。"""
    duplicate_calls = [
        {"id": "c1", "name": "get_weather", "arguments": '{"city": "北京"}'},
        {"id": "c2", "name": "get_weather", "arguments": '{"city": "北京"}'},
    ]

    class _DupGateway(_ScriptedGateway):
        def __init__(self, *args, **kwargs):
            kwargs["round1_calls"] = duplicate_calls
            super().__init__(*args, **kwargs)

    _patch_gateway(env.monkeypatch, gateway_cls=_DupGateway)
    resp = _chat(env, {"messages": [{"role": "user", "content": "北京天气"}]})
    assert resp.status_code == 200
    events = _parse_events(resp.text)
    tool_calls = [d for n, d in events if n == "tool_call"]
    assert len(tool_calls) == 1  # 去重后只剩一次
    assert _FakeRegistry.instances[0].executed == [("get_weather", {"city": "北京"})]
    # 回灌上下文也只有一条 tool 消息
    gateway = _ScriptedGateway.instances[0]
    round2 = [c for c in gateway.calls if c["stream"]][1]["messages"]
    assert len([m for m in round2 if m.get("role") == "tool"]) == 1
    assert "event: done" in resp.text


def test_chat_unknown_tool_recovered_not_aborted(env):
    """模型自造的未知工具：不中断对话，把 2014 失败回灌给模型自行纠正。"""
    weird_calls = [{"id": "", "name": "make_coffee", "arguments": '{"size": "large"}'}]

    class _WeirdGateway(_ScriptedGateway):
        def __init__(self, *args, **kwargs):
            kwargs["round1_calls"] = weird_calls
            super().__init__(*args, **kwargs)

    _patch_gateway(env.monkeypatch, gateway_cls=_WeirdGateway)
    resp = _chat(env, {"messages": [{"role": "user", "content": "来杯咖啡"}]})
    assert resp.status_code == 200
    events = _parse_events(resp.text)
    tool_result = [d for n, d in events if n == "tool_result"][0]
    assert tool_result["result"]["error"]["code"] == ErrorCode.AI_TOOL_CALL_INVALID
    assert "event: error" not in resp.text
    # 失败结果已回灌，模型第二轮给出最终回答
    assert any("北京今天晴" in (d.get("delta") or "") for n, d in events if n == "delta")


def test_chat_write_tool_requires_confirmation(env):
    """写工具不自动执行：done 携带 pendingConfirmation 与待确认调用列表。"""
    write_calls = [{"id": "", "name": "add_plan_item", "arguments": '{"title": "故宫"}'}]

    class _WriteGateway(_ScriptedGateway):
        def __init__(self, *args, **kwargs):
            kwargs["round1_calls"] = write_calls
            super().__init__(*args, **kwargs)

    _patch_gateway(env.monkeypatch, gateway_cls=_WriteGateway)
    resp = _chat(env, {"messages": [{"role": "user", "content": "把故宫加进第一天"}],
                       "trip_id": "trip-1"})
    assert resp.status_code == 200
    events = _parse_events(resp.text)
    tool_call = [d for n, d in events if n == "tool_call"][0]
    assert tool_call["needConfirm"] is True
    assert tool_call["permission"] == "plan:write"
    done = [d for n, d in events if n == "done"][-1]
    assert done["pendingConfirmation"] is True
    assert done["toolCalls"][0]["name"] == "add_plan_item"
    assert done["conversationId"]
    assert _FakeRegistry.instances[0].executed == []  # 写工具绝不自动执行


def test_rename_and_delete_conversation(env):
    """会话管理端点：重命名（PATCH）、删除（DELETE）、列表含标题、越权 404。"""
    conv = AiConversation(user_id="owner-1", title="新对话", scope="global")
    other = AiConversation(user_id="someone-else", title="别人的会话")
    env.db.add_all([conv, other])
    env.db.commit()

    # 重命名
    resp = env.client.patch(f"/api/v1/ai/conversations/{conv.id}", json={"title": "  周末游北京  "})
    assert resp.status_code == 200
    assert resp.json()["data"]["title"] == "周末游北京"
    # 空标题拒绝
    resp = env.client.patch(f"/api/v1/ai/conversations/{conv.id}", json={"title": "   "})
    assert resp.json()["code"] == ErrorCode.VALIDATION
    # 列表已含标题字段
    rows = env.client.get("/api/v1/ai/conversations").json()["data"]
    assert [r["title"] for r in rows] == ["周末游北京"]
    # 越权：别人的会话一律 404（不泄露存在性）
    assert env.client.patch(f"/api/v1/ai/conversations/{other.id}",
                            json={"title": "hack"}).status_code == 404
    # 删除（软删）
    resp = env.client.delete(f"/api/v1/ai/conversations/{conv.id}")
    assert resp.json()["data"] == {"conversationId": conv.id, "deleted": True}
    assert env.client.get("/api/v1/ai/conversations").json()["data"] == []
    assert env.client.get(f"/api/v1/ai/conversations/{conv.id}/messages").status_code == 404
    assert env.client.delete(f"/api/v1/ai/conversations/{conv.id}").status_code == 404


def test_history_messages_render_tool_calls_structured(env):
    """历史会话加载：工具调用/结果还原为结构化数据，供前端渲染卡片。"""
    conv = AiConversation(user_id="owner-1", title="天气查询")
    env.db.add(conv)
    env.db.commit()
    env.db.add_all([
        AiMessage(conversation_id=conv.id, role="user", content="北京天气"),
        AiMessage(conversation_id=conv.id, role="assistant", content="",
                  tool_calls_json=json.dumps([
                      {"id": "c1", "name": "get_weather", "arguments": "{\"city\": \"北京\"}"},
                  ], ensure_ascii=False)),
        AiMessage(conversation_id=conv.id, role="tool", tool_call_id="c1",
                  content=json.dumps({"tool": "get_weather", "result": {"weather": "晴"}}, ensure_ascii=False)),
    ])
    env.db.commit()

    rows = env.client.get(f"/api/v1/ai/conversations/{conv.id}/messages").json()["data"]
    assistant_row = rows[1]
    assert assistant_row["toolCalls"] == [
        {"toolCallId": "c1", "name": "get_weather", "arguments": {"city": "北京"}}
    ]
    tool_row = rows[2]
    assert tool_row["toolCallId"] == "c1"
    assert tool_row["toolResult"] == {"tool": "get_weather", "result": {"weather": "晴"}}
    # 无工具调用的消息也返回空数组，前端可统一处理
    assert rows[0]["toolCalls"] == []
