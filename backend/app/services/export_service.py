"""导出服务：中文 PDF 行程册 + ICS 日历。

PDF 用 reportlab 内置 UnicodeCIDFont('STSong-Light')（Adobe CID 中文字体），
无需打包任何字体文件；ICS 的 VEVENT 时间一律转为 UTC。
纯渲染函数（build_pdf / build_ics）与数据组装函数（render_trip_*）分离，
便于无数据库环境下测试。
"""
from __future__ import annotations

import io
from datetime import date, datetime, timezone
from typing import Any

from icalendar import Calendar, Event
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

from app.core.security import new_id
from app.services.sync_service import row_to_dict

_FONT = "STSong-Light"


def _register_font() -> str:
    try:
        pdfmetrics.registerFont(UnicodeCIDFont(_FONT))
    except Exception:  # noqa: BLE001  重复注册可忽略
        pass
    return _FONT


def _wrap(text: str, font: str, size: float, max_width: float) -> list[str]:
    """按字宽断行（CID 字体支持中文宽度计算）。"""
    lines: list[str] = []
    current = ""
    for ch in str(text or ""):
        if ch == "\n":
            lines.append(current)
            current = ""
            continue
        try:
            width = pdfmetrics.stringWidth(current + ch, font, size)
        except Exception:  # noqa: BLE001  CID 字体宽度不可用时按字符数保守估算
            width = len(current + ch) * size
        if width > max_width:
            lines.append(current)
            current = ch
        else:
            current += ch
    if current:
        lines.append(current)
    return lines or [""]


class _Page:
    """简单的自动分页文本绘制器。"""

    def __init__(self, c: canvas.Canvas, font: str) -> None:
        self.c = c
        self.font = font
        self.w, self.h = A4
        self.y = self.h - 60

    def line(self, text: str, size: float = 10, indent: float = 0, gap: float = 6) -> None:
        for segment in _wrap(text, self.font, size, self.w - 80 - indent):
            if self.y < 55:
                self.c.showPage()
                self.y = self.h - 60
            self.c.setFont(self.font, size)
            self.c.drawString(40 + indent, self.y, segment)
            self.y -= size + gap

    def space(self, amount: float = 10) -> None:
        self.y -= amount
        if self.y < 55:
            self.c.showPage()
            self.y = self.h - 60


def build_pdf(*, trip: dict | None = None, days: list[dict] | None = None,
              places: list[dict] | None = None, bookings: list[dict] | None = None,
              expenses: list[dict] | None = None,
              transports: list[dict] | None = None) -> bytes:
    """生成 PDF：封面 / 按日分页 / 地点 / 预订 / 费用 / 交通。"""
    trip = trip or {}
    days, places = days or [], places or []
    bookings, expenses, transports = bookings or [], expenses or [], transports or []
    font = _register_font()
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, pageCompression=1)
    c.setTitle("FlashTrip Trip Booklet")
    page = _Page(c, font)

    # 封面
    page.line("瞬旅 FlashTrip · 行程册", size=22)
    page.space(24)
    title = str(trip.get("title") or trip.get("name") or "我的行程")
    page.line(title, size=18)
    page.space(16)
    date_range = _trip_date_range(trip)
    if date_range:
        page.line(f"日期：{date_range}", size=11)
    if trip.get("currency"):
        page.line(f"币种：{trip['currency']}", size=11)
    people = _trip_people_line(trip)
    if people:
        page.line(people, size=11)
    page.line(f"共 {len(days)} 天 · {len(places)} 个地点 · {len(bookings)} 条预订", size=11)
    c.showPage()

    # 按日分页
    page.y = page.h - 60
    grouped: dict[str, list[dict]] = {}
    for place in places:
        grouped.setdefault(str(place.get("day_id") or ""), []).append(place)
    if days:
        for day in days:
            label = f"第 {day.get('day_index') or '?'} 天  {day.get('date') or ''}"
            page.line(label, size=15)
            page.line("-" * 24, size=9)
            items = grouped.get(str(day.get("id")), [])
            if not items:
                page.line("（当日暂无安排）", size=10)
            for item in items:
                name = item.get("title") or item.get("name") or item.get("type") or "地点"
                page.line(f"• {name}  {item.get('address') or ''}", size=10, indent=12)
            c.showPage()
            page.y = page.h - 60
    else:
        page.line("全程安排", size=15)
        for item in places:
            name = item.get("title") or item.get("name") or item.get("type") or "地点"
            page.line(f"• {name}", size=10, indent=12)
        c.showPage()
        page.y = page.h - 60

    # 地点清单
    page.line("地点清单", size=15)
    for item in places or []:
        name = item.get("title") or item.get("name") or "地点"
        coord = ""
        if item.get("lng") is not None and item.get("lat") is not None:
            coord = f"（{item['lng']}, {item['lat']} {item.get('coord_system') or 'WGS84'}）"
        page.line(f"• {name} {coord} {item.get('address') or ''}", size=10, indent=12)
    page.space(12)

    # 预订清单
    page.line("预订", size=15)
    for booking in bookings or []:
        page.line(
            f"• [{booking.get('type') or '预订'}] {booking.get('vendor') or ''} "
            f"{booking.get('booking_no') or ''} {booking.get('start_at') or ''} "
            f"{booking.get('amount') or ''} {booking.get('currency') or ''}",
            size=10, indent=12,
        )
    page.space(12)

    # 交通
    page.line("交通", size=15)
    for transport in transports or []:
        page.line(
            f"• {transport.get('mode') or ''} {transport.get('from_name') or ''} -> "
            f"{transport.get('to_name') or ''} {transport.get('depart_at') or ''}",
            size=10, indent=12,
        )
    page.space(12)

    # 费用与合计（含分账模式 / 垫付人）
    page.line("费用", size=15)
    total = 0.0
    for expense in expenses or []:
        try:
            total += float(expense.get("amount") or 0)
        except (TypeError, ValueError):
            pass
        mode = _split_mode_label(expense.get("split_mode"))
        payer = expense.get("paid_by") or ""
        extra = f" [分账:{mode}" + (f" 垫付:{payer}" if payer else "") + "]" if mode or payer else ""
        page.line(
            f"• [{expense.get('category') or '其他'}] {expense.get('amount') or 0} "
            f"{expense.get('currency') or ''} {expense.get('note') or ''}{extra}",
            size=10, indent=12,
        )
    page.line(f"合计：{total:.2f}", size=12)

    c.save()
    return buf.getvalue()


_SPLIT_MODE_LABELS = {
    "equal": "均摊",
    "child_free": "儿童免账",
    "family": "按家庭",
    "custom": "自定义",
    "payer_only": "仅记垫付",
}


def _split_mode_label(mode: Any) -> str:
    key = str(mode or "").strip()
    return _SPLIT_MODE_LABELS.get(key, "")


def _trip_people_line(trip: dict) -> str:
    """封面人数信息：出行人数 / 儿童 / 家庭模式。"""
    count = trip.get("traveler_count")
    if not count:
        return ""
    text = f"出行人数：{count} 人"
    children = trip.get("children_count") or 0
    if children or trip.get("has_children"):
        text += f"（含儿童 {children} 人）"
    if trip.get("family_mode"):
        text += f" · 家庭模式：{trip.get('family_name') or '未命名家庭'}"
    return text


def _as_utc(value: Any) -> datetime:
    """把 date / datetime / ISO 字符串统一为带 UTC 时区的 datetime。"""
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def build_ics(events: list[dict], calendar_name: str = "FlashTrip 行程") -> bytes:
    """由 VEVENT 描述列表生成 ICS（时间恒为 UTC）。"""
    cal = Calendar()
    cal.add("prodid", "-//FlashTrip//Travel Calendar//ZH")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")
    cal.add("x-wr-calname", calendar_name)
    for item in events or []:
        event = Event()
        event.add("uid", str(item.get("uid") or f"{new_id()}@flashtrip"))
        event.add("summary", str(item.get("summary") or "行程"))
        start = _as_utc(item.get("start"))
        event.add("dtstart", start)
        end = _as_utc(item.get("end") or item.get("start"))
        if end < start:
            end = start
        event.add("dtend", end)
        event.add("dtstamp", datetime.now(timezone.utc))
        if item.get("description"):
            event.add("description", str(item["description"]))
        if item.get("location"):
            event.add("location", str(item["location"]))
        cal.add_component(event)
    return cal.to_ical()


def _rows(db, model, value: str | None, limit: int = 300) -> list[dict]:
    """按 trip_id 通用取行；模型/表未就绪时返回空列表而不是中断导出。"""
    try:
        query = db.query(model)
        if value is not None and hasattr(model, "trip_id"):
            query = query.filter(model.trip_id == value)
        return [row_to_dict(row) for row in query.limit(limit).all()]
    except Exception:  # noqa: BLE001
        return []


def _trip_title(trip: dict) -> str:
    return str(trip.get("title") or trip.get("name") or "行程")


def _trip_date_range(trip: dict) -> str:
    start = trip.get("start_date") or trip.get("start_at") or trip.get("date_start") or ""
    end = trip.get("end_date") or trip.get("end_at") or trip.get("date_end") or ""
    return f"{start} ~ {end}" if start or end else ""


def render_trip_pdf(db, trip_id: str) -> bytes:
    """查库组装并生成单行程 PDF。"""
    from app.models.booking import Booking
    from app.models.expense import Expense
    from app.models.transport import Transport

    trip: dict = {}
    days: list[dict] = []
    places: list[dict] = []
    try:
        from app.models.plan import PlanItem
        from app.models.trip import Trip, TripDay

        row = db.get(Trip, trip_id)
        if row is not None:
            trip = row_to_dict(row)
        days = _rows(db, TripDay, trip_id)
        places = _rows(db, PlanItem, trip_id)
    except Exception:  # noqa: BLE001  行程/计划模型未就绪时仍可导出其余数据
        pass
    return build_pdf(
        trip=trip, days=days, places=places,
        bookings=_rows(db, Booking, trip_id),
        expenses=_rows(db, Expense, trip_id),
        transports=_rows(db, Transport, trip_id),
    )


def render_trip_ics(db, trip_id: str | None = None, scope: str = "trip") -> bytes:
    """查库组装并生成 ICS；scope=trip 单行程、scope=all 全部行程。"""
    from app.models.booking import Booking
    from app.models.expense import Expense
    from app.models.transport import Transport

    events: list[dict] = []
    trips: list[dict] = []
    try:
        from app.models.plan import PlanItem
        from app.models.trip import Trip

        trips = _rows(db, Trip, trip_id if scope == "trip" else None)
        for trip in trips:
            tid = str(trip.get("id") or "")
            events.append({
                "uid": f"trip-{tid}@flashtrip",
                "summary": _trip_title(trip),
                "start": trip.get("start_date") or trip.get("start_at"),
                "end": trip.get("end_date") or trip.get("end_at"),
                "description": _trip_date_range(trip),
            })
            for item in _rows(db, PlanItem, tid or None):
                events.append({
                    "uid": f"plan-{item.get('id')}@flashtrip",
                    "summary": str(item.get("title") or item.get("name") or "行程安排"),
                    "start": item.get("start_at") or item.get("date"),
                    "end": item.get("end_at") or item.get("start_at"),
                    "location": item.get("address") or "",
                })
            for booking in _rows(db, Booking, tid or None):
                events.append({
                    "uid": f"booking-{booking.get('id')}@flashtrip",
                    "summary": f"预订 · {booking.get('vendor') or booking.get('type') or ''}",
                    "start": booking.get("start_at"), "end": booking.get("end_at"),
                    "description": str(booking.get("booking_no") or ""),
                })
            for transport in _rows(db, Transport, tid or None):
                events.append({
                    "uid": f"transport-{transport.get('id')}@flashtrip",
                    "summary": f"{transport.get('mode') or '交通'} · "
                               f"{transport.get('from_name') or ''} → {transport.get('to_name') or ''}",
                    "start": transport.get("depart_at"), "end": transport.get("arrive_at"),
                })
            for expense in _rows(db, Expense, tid or None):
                if expense.get("occurred_at"):
                    events.append({
                        "uid": f"expense-{expense.get('id')}@flashtrip",
                        "summary": f"费用 · {expense.get('category') or ''} {expense.get('amount') or ''}",
                        "start": expense.get("occurred_at"),
                    })
    except Exception:  # noqa: BLE001  模型未就绪时返回合法（可能为空）日历
        pass
    name = "FlashTrip 全部行程" if scope == "all" else (_trip_title(trips[0]) if trips else "FlashTrip 行程")
    return build_ics(events, calendar_name=name)
