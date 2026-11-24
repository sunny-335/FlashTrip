"""AI 对话 / 供应商 / 模型 / 工具配置 / 会话管理 API。

POST /ai/chat 为 SSE 流（event: delta|tool_call|tool_result|done|error）：
- delta：{delta, provider?, model?, notice?}，正文增量（文本形式工具调用已被拦截）；
- tool_call：{toolCallId, name, arguments, needConfirm, permission?, confirmed?, unknown?}；
- tool_result：{toolCallId, name, result}；
- done：{conversationId, provider?, model?, content?, tool_calls?, stopped?,
  pendingConfirmation?, toolCalls?}；
- error：{code, message}。
支持 Last-Event-ID 断线补发；写类工具必须由前端二次确认后回传
confirmToolCalls 才会执行，执行时走与人工相同的 require_permission。
会话支持自动标题（截断回退 + 异步低成本生成）、重命名（PATCH）、删除（DELETE）。
"""
from __future__ import annotations

import json
import threading
from collections import deque
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

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
from app.services.ai.gateway import LLMGateway, sse
from app.services.ai.gateway import stop as stop_generation
from app.services.ai.prompts import SYSTEM_PROMPT, TITLE_SYSTEM_PROMPT
from app.services.ai.providers import list_ai_providers, list_models, resolve_provider_configs
from app.services.ai.tools import TOOL_DEFS, ToolRegistry
from app.services.sync_service import row_to_dict

router = APIRouter(tags=["ai"])

_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
# 多轮工具循环上限：查询→整理→再查询→总结等链路需要 >2 轮
_MAX_TOOL_ROUNDS = 6
_DEFAULT_TITLE = "新对话"
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
    """归一化消息数组；兼容旧前端悬浮按钮的扁平 {message: "..."} 载荷。

    客户端伪造的 system 消息一律丢弃：system 提示只能由服务端注入。
    """
    raw = payload.get("messages")
    if not raw and isinstance(payload.get("message"), str) and payload["message"].strip():
        raw = [{"role": "user", "content": payload["message"]}]
    out: list[dict] = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "user")
        if role == "system":
            continue
        message: dict[str, Any] = {
            "role": role,
            "content": item.get("content") or "",
        }
        if item.get("tool_call_id"):
            message["tool_call_id"] = str(item["tool_call_id"])
        if item.get("tool_calls"):
            message["tool_calls"] = item["tool_calls"]
        out.append(message)
    return out[-40:]


def _context(payload: dict) -> dict:
    """把扁平的 scope / tab / path 等页面上下文收进会话 context。"""
    raw = payload.get("context")
    context: dict[str, Any] = dict(raw) if isinstance(raw, dict) else {}
    for key in ("scope", "tab", "path", "trip_id", "tripId"):
        value = payload.get(key)
        if value is not None and key not in context:
            context[key] = value
    return context


def _context_hint(context: dict) -> dict | None:
    """把当前页面上下文（尤其 tab）注入为 system 消息，供模型理解用户所处页面。"""
    tab = str(context.get("tab") or "").strip()
    path = str(context.get("path") or "").strip()
    scope = str(context.get("scope") or "").strip()
    trip_id = str(context.get("trip_id") or context.get("tripId") or "").strip()
    parts = ["以下是当前页面上下文，请据此理解用户意图："]
    if tab:
        parts.append(f"当前标签页 tab={tab}")
    if path:
        parts.append(f"当前路径 path={path}")
    if scope:
        parts.append(f"作用范围 scope={scope}")
    if trip_id:
        parts.append(f"当前行程 trip_id={trip_id}")
    if len(parts) == 1:
        return None
    return {"role": "system", "content": "；".join(parts)}


def _trip_days_hint(db: Session, trip_id: str) -> str | None:
    """把行程的日期范围与行程日清单注入 system 消息。

    没有这层提示时，模型看不到「第 2 天」对应的 day_id，排程就会全堆在同一天。
    """
    if not trip_id:
        return None
    try:
        from app.models.trip import Trip, TripDay

        trip = db.get(Trip, trip_id)
        if trip is None:
            return None
        days = (
            db.query(TripDay)
            .filter(TripDay.trip_id == trip_id, TripDay.deleted_at.is_(None))
            .order_by(TripDay.day_index)
            .all()
        )
    except Exception:  # noqa: BLE001  行程日读取失败不阻断对话
        return None
    if not days:
        return None
    lines = [
        "当前行程的日期与行程日（排程时必须把条目分散到不同天；"
        "新增条目请用 day_id 或 day_index 指定落点）：",
        f"- 行程：{trip.title}",
        f"- 日期范围：{trip.start_date.isoformat() if trip.start_date else '未设置'}"
        f" ~ {trip.end_date.isoformat() if trip.end_date else '未设置'}（共 {len(days)} 天）",
    ]
    for day in days:
        lines.append(
            f"- 第 {day.day_index} 天：day_id={day.id}"
            f"，日期={day.date.isoformat() if day.date else '未设置'}"
        )
    return "\n".join(lines)


def _own_conversation(db: Session, conversation_id: str, user: Any) -> AiConversation | None:
    """取属于当前用户且未删除的会话；不存在/越权一律返回 None。"""
    conv = db.get(AiConversation, conversation_id)
    if conv is None or conv.user_id != getattr(user, "id", None):
        return None
    if getattr(conv, "deleted_at", None) is not None:
        return None
    return conv


def _ensure_conversation(db: Session, user: Any, payload: dict) -> AiConversation:
    conv_id = str(payload.get("conversation_id") or payload.get("conversationId") or "")
    if conv_id:
        existing = _own_conversation(db, conv_id, user)
        if existing is not None:
            # 复用已有会话时合并最新页面上下文（tab 等），供后续轮次使用
            context = _context(payload)
            if context:
                try:
                    merged = json.loads(existing.context_json or "{}")
                    if not isinstance(merged, dict):
                        merged = {}
                except (ValueError, TypeError):
                    merged = {}
                merged.update(context)
                existing.context_json = json.dumps(merged, ensure_ascii=False)
                db.commit()
            return existing
    conv = AiConversation(
        user_id=getattr(user, "id", None),
        trip_id=payload.get("trip_id") or payload.get("tripId") or None,
        scope=str(payload.get("scope") or "global"),
        title=str(payload.get("title") or _DEFAULT_TITLE)[:200],
        context_json=json.dumps(_context(payload), ensure_ascii=False),
    )
    db.add(conv)
    db.commit()
    return conv


# ---------------------------------------------------------------- 标题自动生成
def _fallback_title(text: str) -> str:
    """兜底标题：压缩空白后取前 16 个字符，空内容回退默认标题。"""
    compact = " ".join(str(text or "").split())
    return compact[:16].strip() or _DEFAULT_TITLE


def _sanitize_title(text: str) -> str:
    """清洗模型生成的标题：去装饰字符/引号/多余空白，截断到 12 字。"""
    title = str(text or "").strip(" \t\r\n").strip("\"'`*_#>-：:")
    title = " ".join(title.split())
    return title[:12].strip()


def _generate_title(gateway: LLMGateway, first_user: str, *,
                    provider: str | None, model: str | None) -> str:
    """用同一模型发一条非流式短请求生成标题；任何失败返回空串（调用方回退）。"""
    try:
        raw_events = gateway.chat(
            [
                {"role": "system", "content": TITLE_SYSTEM_PROMPT},
                {"role": "user", "content": f"用户消息：{first_user[:200]}"},
            ],
            provider=provider, model=model, stream=False,
        )
        content = ""
        for raw in raw_events:
            if raw.startswith("event: error"):
                return ""
            if raw.startswith("event: done"):
                try:
                    data = json.loads(raw.split("data: ", 1)[1].strip())
                except (ValueError, IndexError):
                    return ""
                content = str(data.get("content") or "")
                break
    except Exception:  # noqa: BLE001  标题失败必须静默，绝不影响对话
        return ""
    return _sanitize_title(content)


def _update_conversation_title(conversation_id: str, user_id: str | None, title: str,
                               *, expect: str | None = None) -> bool:
    """在独立数据库会话里更新标题（后台线程用，避免跨线程复用请求级会话）。

    expect 非空时仅当当前标题仍匹配才更新，防止覆盖用户手动改过的标题。
    """
    try:
        from app.db.session import get_session

        with get_session()() as db:
            row = db.get(AiConversation, conversation_id)
            if (row is None or row.user_id != user_id
                    or getattr(row, "deleted_at", None) is not None):
                return False
            current = str(row.title or "").strip()
            if expect is not None:
                allowed = ("", _DEFAULT_TITLE) if expect == _DEFAULT_TITLE else (expect,)
                if current not in allowed:
                    return False
            row.title = str(title)[:256]
            db.commit()
            return True
    except Exception:  # noqa: BLE001  标题失败必须静默
        return False


def _record_title_failure(conversation_id: str, user_id: str | None) -> None:
    """标题生成失败只落审计（2015），不打扰用户。"""
    try:
        from app.db.session import get_session
        from app.services.ai.audit import record

        with get_session()() as db:
            record(db, user_id=user_id, action="title_failed", status="error",
                   error="AI_TITLE_GENERATION_FAILED",
                   payload={"conversation_id": conversation_id,
                            "code": ErrorCode.AI_TITLE_GENERATION_FAILED})
    except Exception:  # noqa: BLE001
        pass


def _spawn_title_task(task: Callable[[], None]) -> None:
    """后台线程执行标题任务，绝不阻塞 SSE 流；测试可 monkeypatch 改为同步执行。"""
    threading.Thread(target=task, daemon=True).start()


# ---------------------------------------------------------------- 基础查询端点
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
    # 行内含 id / title / scope / trip_id / created_at / updated_at，标题字段已具备
    return ok([row_to_dict(row) for row in rows], request_id=_rid(request))


@router.post("/ai/conversations")
def create_conversation(request: Request, payload: dict = Body(default={}),
                        db: Session = Depends(get_db),
                        user: Any = Depends(require_permission("ai:use"))):
    conv = _ensure_conversation(db, user, {**payload, "conversation_id": None})
    return ok(row_to_dict(conv), request_id=_rid(request))


@router.patch("/ai/conversations/{conversation_id}")
def rename_conversation(conversation_id: str, request: Request,
                        payload: dict = Body(default={}),
                        db: Session = Depends(get_db),
                        user: Any = Depends(require_permission("ai:use"))):
    """重命名会话；标题不能为空，最长 256 字符。"""
    conv = _own_conversation(db, conversation_id, user)
    if conv is None:
        raise AppError(ErrorCode.NOT_FOUND, "会话不存在")
    title = str(payload.get("title") or "").strip()
    if not title:
        raise AppError(ErrorCode.VALIDATION, "标题不能为空")
    conv.title = title[:256]
    db.commit()
    return ok(row_to_dict(conv), request_id=_rid(request))


@router.delete("/ai/conversations/{conversation_id}")
def delete_conversation(conversation_id: str, request: Request,
                        db: Session = Depends(get_db),
                        user: Any = Depends(require_permission("ai:use"))):
    """删除会话（软删）：会话与消息都标记 deleted_at，不再出现在列表与历史里。"""
    conv = _own_conversation(db, conversation_id, user)
    if conv is None:
        raise AppError(ErrorCode.NOT_FOUND, "会话不存在")
    now = datetime.now(UTC)
    conv.deleted_at = now
    db.query(AiMessage).filter(AiMessage.conversation_id == conversation_id).update(
        {"deleted_at": now}, synchronize_session=False)
    db.commit()
    # 清掉补发日志，避免已删除会话继续被断线补发
    _EVENT_LOG.pop(conversation_id, None)
    _LAST_EVENT_ID.pop(conversation_id, None)
    return ok({"conversationId": conversation_id, "deleted": True}, request_id=_rid(request))


def _loads_or_none(raw: Any) -> Any:
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(str(raw))
    except (ValueError, TypeError):
        return None


def _history_tool_calls(raw: Any) -> list[dict]:
    """把落库的 tool_calls_json 还原为前端可渲染的结构化卡片数据。"""
    calls = _loads_or_none(raw)
    if not isinstance(calls, list):
        return []
    out: list[dict] = []
    for call in calls:
        if not isinstance(call, dict):
            continue
        arguments = call.get("arguments")
        if isinstance(arguments, str):
            arguments = _loads_or_none(arguments)
        out.append({
            "toolCallId": str(call.get("id") or ""),
            "name": str(call.get("name") or ""),
            "arguments": arguments if isinstance(arguments, dict) else {},
        })
    return out


def _message_view(row: AiMessage) -> dict:
    """单条历史消息视图：工具调用/结果还原为结构化数据，而非纯文本。"""
    item = row_to_dict(row)
    item["toolCalls"] = _history_tool_calls(item.get("tool_calls_json"))
    if item.get("tool_call_id"):
        item["toolCallId"] = str(item["tool_call_id"])
    if row.role == "tool":
        item["toolResult"] = _loads_or_none(item.get("content"))
    return item


@router.get("/ai/conversations/{conversation_id}/messages")
def conversation_messages(conversation_id: str, request: Request, db: Session = Depends(get_db),
                          user: Any = Depends(require_user)):
    conv = _own_conversation(db, conversation_id, user)
    if conv is None:
        raise AppError(ErrorCode.NOT_FOUND, "会话不存在")
    rows = (
        db.query(AiMessage)
        .filter(AiMessage.conversation_id == conversation_id)
        .order_by(AiMessage.created_at.asc())
        .all()
    )
    return ok([_message_view(row) for row in rows], request_id=_rid(request))


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
    try:
        cfg = get_config_store().load()
        provider = payload.get("provider") or None
        configs = resolve_provider_configs(cfg, preferred=provider)
    except AppError:
        raise
    except Exception:  # noqa: BLE001  配置解析/解密异常不得变成未捕获的 500
        raise AppError(ErrorCode.AI_PROVIDER_ERROR, "AI 供应商配置读取失败，请检查设置") from None
    if not configs:
        raise AppError(ErrorCode.AI_PROVIDER_ERROR, "未配置可用的 AI 供应商：请填写密钥并选择模型")
    messages = _messages(payload)
    if not messages:
        raise AppError(ErrorCode.VALIDATION, "消息不能为空")
    conv = _ensure_conversation(db, user, payload)
    # 注入 system prompt + 页面上下文提示；后续每轮工具循环都会带上
    full_messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    hint = _context_hint(_context(payload))
    if hint is not None:
        full_messages.append(hint)
    # 注入行程日清单：模型据此把条目分散到不同天，而不是全排在同一天
    context_trip_id = str(
        _context(payload).get("trip_id") or _context(payload).get("tripId")
        or payload.get("trip_id") or payload.get("tripId") or conv.trip_id or ""
    )
    days_hint = _trip_days_hint(db, context_trip_id)
    if days_hint:
        full_messages.append({"role": "system", "content": days_hint})
    full_messages.extend(messages)

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
        _chat_stream(cfg, conv, full_messages, payload, user, db),
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
    first_user = ""
    try:
        last_user = [m for m in messages if m.get("role") == "user"][-1]
        first_user = str(last_user.get("content") or "")
        record_message(db, conversation_id=conv_id, role="user", content=first_user)
    except Exception:  # noqa: BLE001  落库失败不影响对话
        pass

    def start_title_task() -> None:
        """首轮 assistant 完成后异步生成会话标题；绝不阻塞流。"""
        if str(getattr(conv, "title", "") or "").strip() not in ("", _DEFAULT_TITLE):
            return  # 用户已自定义标题（或上一轮已生成），不覆盖

        def worker() -> None:
            try:
                fallback = _fallback_title(first_user)
                if not _update_conversation_title(conv_id, user_id, fallback, expect=_DEFAULT_TITLE):
                    return
                better = _generate_title(gateway, first_user, provider=provider, model=model)
                if better:
                    _update_conversation_title(conv_id, user_id, better, expect=fallback)
                else:
                    _record_title_failure(conv_id, user_id)
            except Exception:  # noqa: BLE001  标题生成失败静默回退
                pass

        _spawn_title_task(worker)

    # 前端二次确认后的写工具：后端执行（走权限）并把结果回灌上下文
    confirmed = payload.get("confirmToolCalls") or payload.get("confirmed_tool_calls") or []
    pre_calls: list[dict] = []
    pre_results: list[dict] = []
    if isinstance(confirmed, list) and confirmed:
        # 删除行程必须先做「是」确认：未确认时整批工具都不执行（含其它工具），
        # 避免误删后无法回退；前端确认卡需回传 confirm: "yes"。
        for item in confirmed:
            if not isinstance(item, dict) or str(item.get("name") or "") != "delete_trip":
                continue
            raw_args: Any = item.get("arguments") or {}
            if isinstance(raw_args, str):
                try:
                    raw_args = json.loads(raw_args)
                except ValueError:
                    raw_args = {}
            if not isinstance(raw_args, dict):
                raw_args = {}
            yes = str(raw_args.get("confirm") or item.get("confirm") or "").strip().lower()
            if yes not in ("yes", "y", "true", "1", "是"):
                yield emit_event("error", {
                    "code": ErrorCode.VALIDATION,
                    "message": "删除行程属于危险操作，需要用户回答「是」二次确认（confirm: \"yes\"）后才可执行",
                })
                return
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
            result_json = json.dumps(result, ensure_ascii=False, default=str)
            yield emit_event("tool_call", {"toolCallId": call_id, "name": name,
                                           "arguments": args, "needConfirm": False, "confirmed": True})
            yield emit_event("tool_result", {"toolCallId": call_id, "name": name, "result": result})
            record_message(db, conversation_id=conv_id, role="tool",
                           tool_call_id=call_id, content=result_json)
            pre_calls.append({"id": call_id, "type": "function",
                              "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}})
            pre_results.append({"role": "tool", "tool_call_id": call_id, "content": result_json})
        if pre_calls:
            messages = messages + [{"role": "assistant", "content": None, "tool_calls": pre_calls}] + pre_results

    # 工具定义：启用时每轮都带上（含确认回放后的收尾轮），模型才能持续结构化调用
    tools = registry.definitions() or None
    round_index = 0
    while round_index < _MAX_TOOL_ROUNDS:
        round_index += 1
        collected: list[dict] = []
        done_raw: str | None = None
        try:
            for raw in gateway.chat(
                messages,
                provider=provider,
                model=model,
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
            if done_raw:
                yield tag(done_raw)
            else:
                yield emit_event("done", {"conversationId": conv_id})
            start_title_task()
            return

        pending_confirmation: list[dict] = []
        executed: list[dict] = []
        llm_tool_calls: list[dict] = []
        # 同一轮内相同工具 + 相同参数的重复调用去重（模型重复抖动时只执行一次）
        seen_calls: set[str] = set()
        for tc in collected:
            name = str(tc.get("name") or "")
            raw_args = tc.get("arguments") or ""
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) and raw_args else (raw_args or {})
            except ValueError:
                args = {}
            if not isinstance(args, dict):
                args = {}
            dedup_key = f"{name}|{json.dumps(args, ensure_ascii=False, sort_keys=True, default=str)}"
            if dedup_key in seen_calls:
                continue
            seen_calls.add(dedup_key)
            call_id = str(tc.get("id") or new_id())
            spec = TOOL_DEFS.get(name, {})
            if not spec:
                # 模型自造/未知的工具名：不中断对话，把失败回灌给模型自行纠正
                message = f"未知工具：{name}"
                failure = {"error": {"code": ErrorCode.AI_TOOL_CALL_INVALID, "message": message}}
                yield emit_event("tool_call", {"toolCallId": call_id, "name": name,
                                               "arguments": args, "needConfirm": False, "unknown": True})
                yield emit_event("tool_result", {"toolCallId": call_id, "name": name, "result": failure})
                failure_json = json.dumps(failure, ensure_ascii=False)
                record_message(db, conversation_id=conv_id, role="tool",
                               tool_call_id=call_id, content=failure_json)
                executed.append({"role": "tool", "tool_call_id": call_id, "content": failure_json})
                llm_tool_calls.append({"id": call_id, "type": "function",
                                       "function": {"name": name, "arguments": raw_args or "{}"}})
                continue
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
            result_json = json.dumps(result, ensure_ascii=False, default=str)
            yield emit_event("tool_result", {"toolCallId": call_id, "name": name, "result": result})
            record_message(db, conversation_id=conv_id, role="tool",
                           tool_call_id=call_id, content=result_json)
            executed.append({"role": "tool", "tool_call_id": call_id, "content": result_json})
            llm_tool_calls.append({"id": call_id, "type": "function",
                                   "function": {"name": name, "arguments": raw_args or "{}"}})

        if pending_confirmation:
            yield emit_event("done", {
                "conversationId": conv_id, "pendingConfirmation": True,
                "toolCalls": pending_confirmation,
            })
            start_title_task()
            return

        if not llm_tool_calls:
            # 本轮全是重复调用被去重：没有新结果可回灌，直接收尾
            if done_raw:
                yield tag(done_raw)
            else:
                yield emit_event("done", {"conversationId": conv_id})
            start_title_task()
            return

        # 回灌工具结果进入下一轮生成（tools/供应商/模型保持不变）
        messages = messages + [{"role": "assistant", "content": None, "tool_calls": llm_tool_calls}] + executed
        if round_index >= _MAX_TOOL_ROUNDS:
            if done_raw:
                yield tag(done_raw)
            else:
                yield emit_event("done", {"conversationId": conv_id})
            start_title_task()
            return
