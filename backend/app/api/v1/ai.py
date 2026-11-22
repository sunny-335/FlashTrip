"""AI 对话 / 供应商 / 模型 / 工具配置 API。

POST /ai/chat 为 SSE 流（event: delta|tool_call|tool_result|done|error），
支持 Last-Event-ID 断线补发；写类工具必须由前端二次确认后回传
confirmToolCalls 才会执行，执行时走与人工相同的 require_permission。
"""
from __future__ import annotations

import json
from collections import deque
from typing import Any, Iterator

from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.v1.deps import get_db, require_permission, require_user
from app.core.config_store import get_config_store
from app.core.errors import AppError, ErrorCode
from app.core.response import ok
from app.core.security import new_id
from app.models.ai import AiConversation, AiMessage
from app.services.ai.audit import record_message
from app.services.ai.gateway import LLMGateway, sse, stop as stop_generation
from app.services.ai.providers import list_ai_providers, list_models, resolve_provider_configs
from app.services.ai.tools import TOOL_DEFS, ToolRegistry
from app.services.sync_service import row_to_dict

router = APIRouter(tags=["ai"])

_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
_MAX_TOOL_ROUNDS = 2
# 断线补发用：每会话最近事件日志（进程内，单进程拓扑）
_EVENT_LOG: dict[str, deque] = {}
_LAST_EVENT_ID: dict[str, int] = {}


def _rid(request: Request) -> str:
    return getattr(request.state, "request_id", "")


def _next_id(conversation_id: str) -> int:
    _LAST_EVENT_ID[conversation_id] = _LAST_EVENT_ID.get(conversation_id, 0) + 1
    return _LAST_EVENT_ID[conversation_id]


def _log_event(conversation_id: str, event_id: int, raw: str) -> None:
    _EVENT_LOG.setdefault(conversation_id, deque(maxlen=300)).append((event_id, raw))


def _replay(conversation_id: str, last_id: int) -> list[str]:
    return [raw for eid, raw in _EVENT_LOG.get(conversation_id, ()) if eid > last_id]


def _messages(payload: dict) -> list[dict]:
    out: list[dict] = []
    for item in payload.get("messages") or []:
        if not isinstance(item, dict):
            continue
        message: dict[str, Any] = {
            "role": str(item.get("role") or "user"),
            "content": item.get("content") or "",
        }
        if item.get("tool_call_id"):
            message["tool_call_id"] = str(item["tool_call_id"])
        if item.get("tool_calls"):
            message["tool_calls"] = item["tool_calls"]
        out.append(message)
    return out[-40:]


def _ensure_conversation(db: Session, user: Any, payload: dict) -> AiConversation:
    conv_id = str(payload.get("conversation_id") or payload.get("conversationId") or "")
    if conv_id:
        existing = db.get(AiConversation, conv_id)
        if existing is not None and existing.user_id == getattr(user, "id", None):
            return existing
    conv = AiConversation(
        user_id=getattr(user, "id", None),
        trip_id=payload.get("trip_id") or payload.get("tripId") or None,
        scope=str(payload.get("scope") or "global"),
        title=str(payload.get("title") or "新对话")[:200],
        context_json=json.dumps(payload.get("context") or {}, ensure_ascii=False),
    )
    db.add(conv)
    db.commit()
    return conv


@router.get("/ai/providers")
def providers(request: Request, user: Any = Depends(require_user)):
    return ok(list_ai_providers(get_config_store().load()), request_id=_rid(request))


@router.get("/ai/models")
def models(request: Request, provider: str = Query(default=""),
           user: Any = Depends(require_user)):
    if not provider:
        raise AppError(ErrorCode.VALIDATION, "请指定 provider")
    return ok(list_models(provider, cfg=get_config_store().load()), request_id=_rid(request))


@router.get("/ai/conversations")
def list_conversations(request: Request, db: Session = Depends(get_db),
                       user: Any = Depends(require_user)):
    rows = (
        db.query(AiConversation)
        .filter(AiConversation.user_id == getattr(user, "id", None))
        .order_by(AiConversation.created_at.desc())
        .all()
    )
    return ok([row_to_dict(row) for row in rows], request_id=_rid(request))


@router.post("/ai/conversations")
def create_conversation(request: Request, payload: dict = Body(default={}),
                        db: Session = Depends(get_db),
                        user: Any = Depends(require_permission("ai:use"))):
    conv = _ensure_conversation(db, user, {**payload, "conversation_id": None})
    return ok(row_to_dict(conv), request_id=_rid(request))


@router.get("/ai/conversations/{conversation_id}/messages")
def conversation_messages(conversation_id: str, request: Request, db: Session = Depends(get_db),
                          user: Any = Depends(require_user)):
    conv = db.get(AiConversation, conversation_id)
    if conv is None or conv.user_id != getattr(user, "id", None):
        raise AppError(ErrorCode.NOT_FOUND, "会话不存在")
    rows = (
        db.query(AiMessage)
        .filter(AiMessage.conversation_id == conversation_id)
        .order_by(AiMessage.created_at.asc())
        .all()
    )
    return ok([row_to_dict(row) for row in rows], request_id=_rid(request))


@router.get("/ai/tools")
def get_tools(request: Request, user: Any = Depends(require_user)):
    return ok(ToolRegistry.config(get_config_store().load()), request_id=_rid(request))


@router.put("/ai/tools/config")
def put_tools_config(request: Request, payload: dict = Body(default={}),
                     user: Any = Depends(require_permission("ai:use"))):
    return ok(ToolRegistry.set_config(payload), request_id=_rid(request))


@router.post("/ai/chat/{conversation_id}/stop")
def stop_chat(conversation_id: str, request: Request,
              user: Any = Depends(require_permission("ai:use"))):
    stop_generation(conversation_id)
    return ok({"conversationId": conversation_id, "stopped": True}, request_id=_rid(request))


@router.post("/ai/chat")
def chat(request: Request, payload: dict = Body(default={}), db: Session = Depends(get_db),
         user: Any = Depends(require_permission("ai:use"))):
    """SSE 流式对话；配置错误在流开始前以标准 JSON 错误返回。"""
    cfg = get_config_store().load()
    provider = payload.get("provider") or None
    if not resolve_provider_configs(cfg, preferred=provider):
        raise AppError(ErrorCode.AI_PROVIDER_ERROR, "未配置可用的 AI 供应商：请填写密钥并选择模型")
    messages = _messages(payload)
    if not messages:
        raise AppError(ErrorCode.VALIDATION, "消息不能为空")
    conv = _ensure_conversation(db, user, payload)

    raw_last = request.headers.get("Last-Event-ID") or payload.get("last_event_id") or payload.get("lastEventId")
    if raw_last:
        try:
            last_id = int(raw_last)
        except (TypeError, ValueError):
            last_id = 0
        cached = _replay(conv.id, last_id)
        if cached:
            return StreamingResponse(iter(cached), media_type="text/event-stream", headers=_SSE_HEADERS)

    return StreamingResponse(
        _chat_stream(cfg, conv, messages, payload, user, db),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


def _chat_stream(cfg: dict, conv: AiConversation, messages: list[dict], payload: dict,
                 user: Any, db: Session) -> Iterator[str]:
    conv_id = conv.id
    user_id = getattr(user, "id", None)
    trip_id = payload.get("trip_id") or payload.get("tripId") or conv.trip_id
    provider = payload.get("provider") or None
    model = payload.get("model") or None
    registry = ToolRegistry(cfg=cfg, db=db, user=user, trip_id=trip_id)
    gateway = LLMGateway(cfg=cfg, db=db)

    def emit_event(name: str, data: dict) -> str:
        event_id = _next_id(conv_id)
        raw = sse(name, data, event_id=event_id)
        _log_event(conv_id, event_id, raw)
        return raw

    def tag(raw: str) -> str:
        """为 gateway 产出的事件补上递增 id 并记入补发日志。"""
        event_id = _next_id(conv_id)
        tagged = f"id: {event_id}\n{raw}"
        _log_event(conv_id, event_id, tagged)
        return tagged

    # 用户消息落库（只记录最后一条，避免重放时重复）
    try:
        last_user = [m for m in messages if m.get("role") == "user"][-1]
        record_message(db, conversation_id=conv_id, role="user",
                       content=str(last_user.get("content") or ""))
    except Exception:  # noqa: BLE001  落库失败不影响对话
        pass

    # 前端二次确认后的写工具：后端执行（走权限）并把结果回灌上下文
    confirmed = payload.get("confirmToolCalls") or payload.get("confirmed_tool_calls") or []
    pre_calls: list[dict] = []
    pre_results: list[dict] = []
    if isinstance(confirmed, list) and confirmed:
        for item in confirmed:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "")
            args: Any = item.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {}
            if not isinstance(args, dict):
                args = {}
            call_id = str(item.get("toolCallId") or item.get("id") or new_id())
            try:
                result = registry.execute(name, args, confirmed=True)
            except AppError as exc:
                yield emit_event("error", {"code": exc.code, "message": exc.message})
                return
            yield emit_event("tool_call", {"toolCallId": call_id, "name": name,
                                           "arguments": args, "needConfirm": False, "confirmed": True})
            yield emit_event("tool_result", {"toolCallId": call_id, "name": name, "result": result})
            pre_calls.append({"id": call_id, "type": "function",
                              "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}})
            pre_results.append({"role": "tool", "tool_call_id": call_id,
                                "content": json.dumps(result, ensure_ascii=False, default=str)})
        if pre_calls:
            messages = messages + [{"role": "assistant", "content": None, "tool_calls": pre_calls}] + pre_results

    tools = None if confirmed else registry.definitions()
    round_index = 0
    while round_index < _MAX_TOOL_ROUNDS:
        round_index += 1
        collected: list[dict] = []
        done_raw: str | None = None
        try:
            for raw in gateway.chat(
                messages,
                provider=provider if round_index == 1 else None,
                model=model if round_index == 1 else None,
                stream=True,
                user_id=user_id, trip_id=trip_id, conversation_id=conv_id,
                tools=tools, tool_calls_out=collected,
            ):
                if raw.startswith("event: error"):
                    yield tag(raw)
                    return
                if raw.startswith("event: done"):
                    done_raw = raw
                    continue
                yield tag(raw)
        except AppError as exc:
            yield emit_event("error", {"code": exc.code, "message": exc.message})
            return
        except Exception:  # noqa: BLE001
            yield emit_event("error", {"code": ErrorCode.INTERNAL, "message": "对话生成失败"})
            return

        if not collected:
            yield tag(done_raw) if done_raw else emit_event("done", {"conversationId": conv_id})
            return

        pending_confirmation: list[dict] = []
        executed: list[dict] = []
        llm_tool_calls: list[dict] = []
        for tc in collected:
            name = str(tc.get("name") or "")
            raw_args = tc.get("arguments") or ""
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) and raw_args else (raw_args or {})
            except ValueError:
                args = {}
            if not isinstance(args, dict):
                args = {}
            call_id = str(tc.get("id") or new_id())
            spec = TOOL_DEFS.get(name, {})
            if spec.get("write"):
                # 写工具绝不自动执行，交给前端确认卡
                yield emit_event("tool_call", {
                    "toolCallId": call_id, "name": name, "arguments": args,
                    "needConfirm": True, "permission": spec.get("permission"),
                    "message": "该操作会修改行程数据，请在前端确认后执行",
                })
                pending_confirmation.append({"toolCallId": call_id, "name": name, "arguments": args})
                continue
            yield emit_event("tool_call", {"toolCallId": call_id, "name": name,
                                           "arguments": args, "needConfirm": False})
            try:
                result = registry.execute(name, args, confirmed=False)
            except AppError as exc:
                yield emit_event("error", {"code": exc.code, "message": exc.message})
                return
            yield emit_event("tool_result", {"toolCallId": call_id, "name": name, "result": result})
            executed.append({"role": "tool", "tool_call_id": call_id,
                             "content": json.dumps(result, ensure_ascii=False, default=str)})
            llm_tool_calls.append({"id": call_id, "type": "function",
                                   "function": {"name": name, "arguments": raw_args or "{}"}})

        if pending_confirmation:
            yield emit_event("done", {
                "conversationId": conv_id, "pendingConfirmation": True,
                "toolCalls": pending_confirmation,
            })
            return

        # 回灌只读工具结果，进入第二轮生成最终回答
        messages = messages + [{"role": "assistant", "content": None, "tool_calls": llm_tool_calls}] + executed
        tools = None
        if round_index >= _MAX_TOOL_ROUNDS:
            yield tag(done_raw) if done_raw else emit_event("done", {"conversationId": conv_id})
            return
