"""LLM 网关：原生 openai SDK + SSE 流式 + 重试 + 跨供应商降级 + 审计。

- 模型名绝不硬编码：来自向导配置的动态 model 或 /models 探测结果。
- 统一超时 60s、指数退避重试 3 次、按 priority 跨供应商降级。
- 主供应商故障不静默：产出 notice 增量、落审计；全部失败时 error 事件明确 2004。
- token / cost / latency 落 ai_messages 与 ai_audit_logs。
"""
from __future__ import annotations

import json
import time
from decimal import Decimal
from typing import Any, Iterator

from openai import OpenAI

from app.core.config_store import get_config_store
from app.core.errors import AppError, ErrorCode
from app.services.ai.audit import record, record_message
from app.services.ai.providers import resolve_provider_configs

_TIMEOUT = 60.0
_RETRIES = 3
_STOPPED: set[str] = set()


def sse(event: str, data: Any, event_id: str | int | None = None) -> str:
    """构造单条 SSE 事件字符串（data 恒为 JSON）。"""
    prefix = f"id: {event_id}\n" if event_id is not None else ""
    return f"{prefix}event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def stop(conversation_id: str) -> None:
    """请求中断某会话正在进行的生成。"""
    if conversation_id:
        _STOPPED.add(conversation_id)


def clear_stop(conversation_id: str) -> None:
    _STOPPED.discard(conversation_id)


def is_stopped(conversation_id: str | None) -> bool:
    return bool(conversation_id and conversation_id in _STOPPED)


def _make_client(base_url: str, key: str, timeout: float = _TIMEOUT) -> Any:
    """SDK 客户端工厂（测试可 monkeypatch 本函数或 LLMGateway.client_factory）。"""
    return OpenAI(api_key=key, base_url=base_url, timeout=timeout, max_retries=0)


class LLMGateway:
    def __init__(self, cfg: dict | None = None, db=None, client_factory=None) -> None:
        self.cfg = cfg if cfg is not None else get_config_store().load()
        self.db = db
        self.client_factory = client_factory or _make_client

    def chat(self, messages: list[dict], provider: str | None = None, model: str | None = None,
             stream: bool = True, *, user_id: str | None = None, trip_id: str | None = None,
             conversation_id: str | None = None, tools: list[dict] | None = None,
             tool_calls_out: list[dict] | None = None) -> Iterator[str]:
        """返回产出 SSE 事件字符串的迭代器。

        本方法本身不是生成器：配置缺失会在调用时立刻抛 AppError（便于异常处理器
        返回标准 JSON 包装），而流式过程中的故障通过 event: error 表达。
        """
        candidates = resolve_provider_configs(self.cfg, preferred=provider)
        if not candidates:
            raise AppError(ErrorCode.AI_PROVIDER_ERROR, "未配置可用的 AI 供应商：请填写密钥并选择模型")
        if provider and all(c["id"] != provider for c in candidates):
            # 指定的主供应商未配置：明确报错，不静默改用其它供应商
            raise AppError(ErrorCode.AI_PROVIDER_ERROR, f"AI 供应商 {provider} 未配置密钥或模型")
        return self._stream(
            messages=messages, candidates=candidates, model=model, stream=stream,
            tools=tools, tool_calls_out=tool_calls_out, user_id=user_id,
            trip_id=trip_id, conversation_id=conversation_id,
        )

    @staticmethod
    def _cost(cand: dict, prompt_tokens: int, completion_tokens: int) -> Decimal:
        """按向导可选单价估算成本；未配置单价则为 0（不臆造价格）。"""
        try:
            rate_in = Decimal(str(cand.get("cost_per_1k_prompt") or 0))
            rate_out = Decimal(str(cand.get("cost_per_1k_completion") or 0))
            return (rate_in * prompt_tokens + rate_out * completion_tokens) / Decimal(1000)
        except Exception:  # noqa: BLE001
            return Decimal(0)

    def _stream(self, *, messages, candidates, model, stream, tools, tool_calls_out,
                user_id, trip_id, conversation_id) -> Iterator[str]:
        failures: list[str] = []
        for index, cand in enumerate(candidates):
            # 主供应商可用调用方指定的模型；降级时用该供应商自身配置的动态模型
            use_model = model if (index == 0 and model) else cand["model"]
            for attempt in range(_RETRIES):
                if conversation_id and is_stopped(conversation_id):
                    clear_stop(conversation_id)
                    yield sse("done", {"stopped": True, "provider": cand["id"], "model": use_model})
                    return
                started = time.perf_counter()
                try:
                    client = self.client_factory(cand["base_url"], cand["key"], cand["timeout_s"])
                    kwargs: dict[str, Any] = {"model": use_model, "messages": messages}
                    if tools:
                        kwargs["tools"] = tools

                    text_parts: list[str] = []
                    tool_slots: dict[int, dict] = {}
                    prompt_tokens = 0
                    completion_tokens = 0

                    if stream:
                        chunks = client.chat.completions.create(
                            stream=True, stream_options={"include_usage": True}, **kwargs
                        )
                        for chunk in chunks:
                            if conversation_id and is_stopped(conversation_id):
                                clear_stop(conversation_id)
                                record(self.db, user_id=user_id, trip_id=trip_id,
                                       provider=cand["id"], model=use_model, action="chat_stopped")
                                yield sse("done", {"stopped": True, "provider": cand["id"], "model": use_model})
                                return
                            usage = getattr(chunk, "usage", None)
                            if usage is not None:
                                prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
                                completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
                            choices = getattr(chunk, "choices", None) or []
                            if not choices:
                                continue
                            delta = getattr(choices[0], "delta", None)
                            if delta is None:
                                continue
                            piece = getattr(delta, "content", None)
                            if piece:
                                text_parts.append(piece)
                                yield sse("delta", {"delta": piece, "provider": cand["id"], "model": use_model})
                            for tc in (getattr(delta, "tool_calls", None) or []):
                                idx = int(getattr(tc, "index", 0) or 0)
                                slot = tool_slots.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                                if getattr(tc, "id", None):
                                    slot["id"] = tc.id
                                fn = getattr(tc, "function", None)
                                if fn is not None:
                                    name = getattr(fn, "name", None)
                                    if name and not slot["name"]:
                                        slot["name"] = name
                                    args = getattr(fn, "arguments", None)
                                    if args:
                                        slot["arguments"] += args
                    else:
                        resp = client.chat.completions.create(stream=False, **kwargs)
                        usage = getattr(resp, "usage", None)
                        if usage is not None:
                            prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
                            completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
                        message = resp.choices[0].message
                        if getattr(message, "content", None):
                            text_parts.append(message.content)
                            yield sse("delta", {"delta": message.content, "provider": cand["id"], "model": use_model})
                        for tc in (getattr(message, "tool_calls", None) or []):
                            fn = getattr(tc, "function", None)
                            tool_slots[len(tool_slots)] = {
                                "id": getattr(tc, "id", "") or "",
                                "name": getattr(fn, "name", "") if fn is not None else "",
                                "arguments": getattr(fn, "arguments", "") if fn is not None else "",
                            }

                    latency_ms = int((time.perf_counter() - started) * 1000)
                    content = "".join(text_parts)
                    tool_calls = [tool_slots[k] for k in sorted(tool_slots)]
                    if tool_calls_out is not None:
                        tool_calls_out.extend(tool_calls)
                    cost = self._cost(cand, prompt_tokens, completion_tokens)
                    record(
                        self.db, user_id=user_id, trip_id=trip_id, provider=cand["id"],
                        model=use_model, action="chat", status="ok",
                        payload={"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                                 "cost": str(cost), "latency_ms": latency_ms, "tool_calls": tool_calls},
                    )
                    if conversation_id:
                        record_message(
                            self.db, conversation_id=conversation_id, role="assistant",
                            content=content, tool_calls_json=tool_calls or None,
                            provider=cand["id"], model=use_model,
                            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                            cost=cost, latency_ms=latency_ms,
                        )
                    yield sse("done", {
                        "provider": cand["id"], "model": use_model, "content": content,
                        "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                        "cost": float(cost), "latency_ms": latency_ms, "tool_calls": tool_calls,
                    })
                    return
                except AppError:
                    raise
                except Exception as exc:  # noqa: BLE001  只记异常类型，绝不记录含密钥的 URL/正文
                    failures.append(f"{cand['id']}/{type(exc).__name__}")
                    record(self.db, user_id=user_id, trip_id=trip_id, provider=cand["id"],
                           model=use_model, action="provider_error", status="error",
                           error=type(exc).__name__, payload={"attempt": attempt + 1})
                    if attempt < _RETRIES - 1:
                        time.sleep(0.5 * (2**attempt))  # 指数退避 0.5s / 1s / 2s
                        continue
                    break

            # 该供应商重试耗尽：明确提示降级，绝不静默切换
            if index < len(candidates) - 1:
                yield sse("delta", {
                    "delta": "",
                    "notice": f"供应商 {cand['id']} 调用失败，正在按优先级切换到 {candidates[index + 1]['id']}",
                    "failedProvider": cand["id"],
                })

        record(self.db, user_id=user_id, trip_id=trip_id, action="chat_failed",
               status="error", error="；".join(failures))
        yield sse("error", {
            "code": ErrorCode.AI_PROVIDER_ERROR,
            "message": "AI 供应商调用失败（" + "、".join(c["id"] for c in candidates) + "），请检查密钥、模型与网络",
            "failures": failures,
        })
