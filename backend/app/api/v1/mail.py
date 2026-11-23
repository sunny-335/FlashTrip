"""邮件 API：脱敏配置、测试发信、日志、模板，以及手动触发行程天气建议邮件。"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.v1.deps import get_db, require_permission
from app.core.errors import AppError, ErrorCode
from app.core.response import ok
from app.models.trip import Trip
from app.services import mail_service, weather_service
from app.services.sync_service import row_to_dict

router = APIRouter(tags=["mail"])


def _rid(request: Request) -> str:
    return getattr(getattr(request, "state", None), "request_id", "") or ""


@router.get("/mail/config")
def get_config(request: Request, user: Any = Depends(require_permission("trip:settings"))):
    """脱敏配置：password_enc 只回 has_password 布尔。"""
    return ok(mail_service.get_mail_config(), request_id=_rid(request))


@router.put("/mail/config")
def put_config(request: Request, cfg: dict | None = Body(default=None),
               user: Any = Depends(require_permission("trip:settings"))):
    return ok(mail_service.save_mail_config(cfg or {}), request_id=_rid(request))


@router.post("/mail/test")
def test(request: Request, override: dict | None = Body(default=None),
         user: Any = Depends(require_permission("trip:settings"))):
    return ok(mail_service.test_mail(override), request_id=_rid(request))


@router.get("/mail/logs")
def logs(request: Request, limit: int = Query(default=50, ge=1, le=200),
         db: Session = Depends(get_db),
         user: Any = Depends(require_permission("trip:settings"))):
    return ok(mail_service.list_logs(db, limit), request_id=_rid(request))


@router.get("/mail/templates")
def templates(request: Request, user: Any = Depends(require_permission("trip:settings"))):
    return ok(mail_service.list_templates(), request_id=_rid(request))


# ---------------------------------------------------------------- 天气建议邮件

def _trip_payload(db: Session, trip_id: str) -> dict:
    trip = db.get(Trip, trip_id)
    if trip is None:
        raise AppError(ErrorCode.NOT_FOUND, "行程不存在")
    data = row_to_dict(trip)
    return {
        "trip_id": trip.id,
        "id": trip.id,
        "title": data.get("title") or "我的行程",
        "destination": data.get("destination") or "",
        "start_date": data.get("start_date") or "",
        "end_date": data.get("end_date") or "",
        "traveler_count": int(data.get("traveler_count") or 1),
        "children_count": int(data.get("children_count") or 0),
    }


def _empty_weather(message: str) -> dict:
    """天气不可用时的归一化占位，保证下游渲染不抛异常；缺失字段一律为 None。"""
    return {
        "provider": "",
        "city": "",
        "current": {
            "weather": None, "temperature": None, "humidity": None,
            "wind": None, "report_time": None, "alerts": [],
        },
        "forecast": [],
        "advice_hints": [message],
        "cached": True,
    }


def _llm_advice(prompt: str, db: Session) -> str | None:
    """调用 LLMGateway 生成建议；AI 未配置/不可用返回 None，由调用方降级。"""
    try:
        from app.services.ai.gateway import LLMGateway

        events = LLMGateway(db=db).chat(
            [
                {"role": "system", "content": "你是专业旅行管家，用简洁中文分点作答，不编造信息。"},
                {"role": "user", "content": prompt},
            ],
            stream=False,
        )
        text = ""
        for event in events:
            for line in str(event).splitlines():
                if not line.startswith("data:"):
                    continue
                try:
                    payload = json.loads(line[5:].strip())
                except (ValueError, TypeError):
                    continue
                if isinstance(payload, dict) and payload.get("content"):
                    text = str(payload["content"])
        return text.strip() or None
    except Exception:
        return None


def _fallback_advice(weather: dict) -> str:
    """AI 不可用时用天气提示词拼出可读的 Markdown 建议（供结构化渲染）。"""
    current = weather.get("current") or {}
    hints = weather.get("advice_hints") or []
    temp = current.get("temperature")
    temp_text = f"{temp:.0f}℃" if isinstance(temp, (int, float)) else "暂无气温"
    lines = [
        f"当前天气：{current.get('weather') or '暂无实况'}，{temp_text}，{current.get('wind') or '风力未知'}。",
        "出行建议：",
    ]
    lines.extend(f"- {hint}" for hint in hints)
    if len(lines) == 2:
        lines.append("- 天气适宜出行，祝你旅途愉快")
    return "\n".join(lines)


def _build_weather_advice(db: Session, trip_id: str) -> tuple[dict, dict, str]:
    """拉天气 -> LLM 生成建议（不可用则降级）；纯计算，不发送任何邮件。"""
    trip = _trip_payload(db, trip_id)
    city = trip.get("destination") or ""
    try:
        weather = (
            weather_service.fetch_weather(city, db=db)
            if city else _empty_weather("未设置目的地，暂无法获取天气")
        )
    except Exception as exc:  # noqa: BLE001  天气不可用降级，不阻断预览/发送
        message = getattr(exc, "message", None) or "天气服务暂不可用，请稍后再试"
        weather = _empty_weather(message)
    prompt = weather_service.build_advice_prompt(trip, weather)
    advice = _llm_advice(prompt, db) or _fallback_advice(weather)
    return trip, weather, advice


@router.post("/trips/{trip_id}/weather-advice")
def weather_advice_preview(trip_id: str, request: Request, db: Session = Depends(get_db),
                           user: Any = Depends(require_permission("trip:settings"))):
    """【预览】生成天气与出行建议，纯读不发送，供详情页「天气与出行建议」使用。"""
    trip, weather, advice = _build_weather_advice(db, trip_id)
    subject, html_body = mail_service.build_advice_email(trip, advice, weather)
    return ok(
        {
            "sent": 0, "failed": 0, "dry_run": True,
            "advice": advice, "subject": subject, "preview_html": html_body,
            "weather": weather,
        },
        request_id=_rid(request),
    )


@router.post("/trips/{trip_id}/weather-advice/send")
def weather_advice_send(trip_id: str, request: Request, db: Session = Depends(get_db),
                        user: Any = Depends(require_permission("trip:settings"))):
    """【发送】显式手动触发行程天气建议邮件给默认收件人。"""
    trip, weather, advice = _build_weather_advice(db, trip_id)
    result = mail_service.send_weather_advice(db, trip, advice=advice, weather=weather)
    return ok(
        {"sent": result["sent"], "failed": result["failed"], "advice": advice},
        request_id=_rid(request),
    )
