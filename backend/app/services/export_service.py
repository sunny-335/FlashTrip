"""导出服务：中文 PDF 行程手册 + ICS 日历。

PDF 采用 reportlab 画布手工排版，结构为：封面（品牌色块）/ 行程总览 / 分日行程
（色块标题条 + 地点卡片 + 当日交通与小计）/ 预订与交通表格 / 费用汇总（分类表 +
占比条 + 总计）。色值与 frontend/src/style.css 的 :root 令牌保持一致（主色
#0e9f8e）。中文使用内置 UnicodeCIDFont('STSong-Light')，无需打包字体文件；
ICS 的 VEVENT 时间一律转为 UTC。纯渲染函数（build_pdf / build_ics）与数据组装
函数（render_trip_*）分离，便于无数据库环境下测试。
"""
from __future__ import annotations

import io
from datetime import date, datetime, timezone
from typing import Any

from icalendar import Calendar, Event
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

from app.core.security import new_id
from app.services.sync_service import row_to_dict

_FONT = "STSong-Light"

# ------------------------------------------------------------------ 品牌色与版面
_PRIMARY = HexColor("#0e9f8e")       # 主色（--primary）
_PRIMARY_DARK = HexColor("#0b6f63")  # 深主色（--accent-foreground）
_ACCENT = HexColor("#e8f5f2")        # 浅主色块（--accent）
_SOFT = HexColor("#cdeee8")          # 品牌色块上的次级文字
_CARD = HexColor("#f3f5f3")          # 卡片底色（--muted）
_MUTED = HexColor("#6b756f")         # 次级文字（--muted-foreground）
_LINE = HexColor("#e4e8e5")          # 分隔线（--border）
_TEXT = HexColor("#1c211f")          # 正文（--foreground）
_WHITE = HexColor("#ffffff")

_PAGE_W, _PAGE_H = A4
_MARGIN = 48.0
_CONTENT_W = _PAGE_W - 2 * _MARGIN
_BOTTOM = 56.0    # 页脚线之上
_TOP = 60.0       # 页眉线之下

_WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
_CATEGORY_LABELS = {
    "food": "餐饮", "lodging": "住宿", "hotel": "住宿", "transport": "交通",
    "ticket": "门票", "shopping": "购物", "other": "其他",
}
_BOOKING_TYPE_LABELS = {"flight": "机票", "hotel": "酒店", "train": "火车", "ticket": "门票", "other": "其他"}
_MODE_LABELS = {
    "flight": "飞机", "train": "火车", "car": "自驾", "bus": "大巴",
    "ferry": "轮渡", "walk": "步行", "other": "其他",
}


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


def _ellipsize(text: Any, font: str, size: float, max_w: float) -> str:
    """单行截断（页眉等固定区域用，避免与右侧文字碰撞）。"""
    text = str(text or "")
    try:
        if pdfmetrics.stringWidth(text, font, size) <= max_w:
            return text
        while text and pdfmetrics.stringWidth(text + "…", font, size) > max_w:
            text = text[:-1]
    except Exception:  # noqa: BLE001
        return text[: max(4, int(max_w / size))]
    return text + "…"


# ------------------------------------------------------------------ 取值与格式化
def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt_amount(value: float) -> str:
    return f"{value:,.2f}"


def _to_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _fmt_hm(value: Any) -> str:
    dt = _to_datetime(value)
    return dt.strftime("%H:%M") if dt else ""


def _fmt_dhm(value: Any) -> str:
    dt = _to_datetime(value)
    if dt is not None:
        return dt.strftime("%m-%d %H:%M")
    return str(value or "").strip()[:16]


def _fmt_md(value: Any) -> str:
    dt = _to_datetime(value)
    return dt.strftime("%m-%d") if dt is not None else str(value or "").strip()[-5:]


def _fmt_day(value: Any) -> str:
    dt = _to_datetime(value)
    return dt.strftime("%Y-%m-%d") if dt is not None else str(value or "").strip()


def _weekday_cn(value: Any) -> str:
    dt = _to_datetime(value)
    return _WEEKDAYS[dt.weekday()] if dt is not None else ""


def _fmt_duration(value: Any) -> str:
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        return ""
    if minutes <= 0:
        return ""
    hours, rem = divmod(minutes, 60)
    if not hours:
        return f"{minutes} 分钟"
    if not rem:
        return f"{hours} 小时"
    if rem == 30:
        return f"{hours}.5 小时"
    return f"{hours} 小时 {rem} 分钟"


def _label(mapping: dict[str, str], value: Any) -> str:
    key = str(value or "").strip()
    if not key:
        return mapping.get("other", "其他")
    return mapping.get(key, key)


def _expense_currency(expenses: list[dict]) -> str:
    for item in expenses or []:
        cur = str(item.get("currency") or "").strip()
        if cur:
            return cur
    return ""


def _group_by(rows: list[dict], key: str) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for row in rows or []:
        grouped.setdefault(str(row.get(key) or ""), []).append(row)
    return grouped


def _sorted_by_time(rows: list[dict], key: str) -> list[dict]:
    def sort_key(row: dict) -> tuple:
        dt = _to_datetime(row.get(key))
        return (dt is None, dt or datetime.min, str(row.get("sort_key") or ""))

    return sorted(rows or [], key=sort_key)


def _cover_people(trip: dict) -> str:
    """封面人数信息：出行人数 / 儿童 / 家庭模式。"""
    count = trip.get("traveler_count")
    if not count:
        return ""
    text = f"{count} 人"
    children = trip.get("children_count") or 0
    if children or trip.get("has_children"):
        text += f"（含儿童 {children} 人）"
    if trip.get("family_mode"):
        text += f" · 家庭模式：{trip.get('family_name') or '未命名家庭'}"
    return text


# ------------------------------------------------------------------ 画布封装
class _Book:
    """带页眉（行程名）/ 页脚（页码）与自动分页的画布封装；封面页无页眉页脚。"""

    def __init__(self, c: canvas.Canvas, font: str, title: str) -> None:
        self.c = c
        self.font = font
        self.title = title
        self.page_no = 1
        self.y = _PAGE_H - _TOP

    def _decorate(self) -> None:
        if self.page_no <= 1:  # 封面保持留白，不加页眉页脚
            return
        c = self.c
        c.setFillColor(_MUTED)
        c.setFont(self.font, 8)
        c.drawString(_MARGIN, 34, "瞬旅 FlashTrip · 行程手册")
        c.drawRightString(_PAGE_W - _MARGIN, 34, f"第 {self.page_no} 页")
        c.setStrokeColor(_LINE)
        c.setLineWidth(0.5)
        c.line(_MARGIN, 46, _PAGE_W - _MARGIN, 46)
        c.setFont(self.font, 8.5)
        c.drawString(_MARGIN, _PAGE_H - 36, _ellipsize(self.title, self.font, 8.5, _CONTENT_W - 70))
        c.drawRightString(_PAGE_W - _MARGIN, _PAGE_H - 36, "FlashTrip")
        c.line(_MARGIN, _PAGE_H - 44, _PAGE_W - _MARGIN, _PAGE_H - 44)

    def break_page(self) -> None:
        self._decorate()
        self.c.showPage()
        self.page_no += 1
        self.y = _PAGE_H - _TOP

    def finish(self) -> None:
        """收尾：为当前页补画页眉页脚（save 会自动结束最后一页）。"""
        self._decorate()

    def ensure(self, need: float) -> None:
        if self.y - need < _BOTTOM:
            self.break_page()

    def gap(self, height: float) -> None:
        self.y -= height
        if self.y < _BOTTOM:
            self.break_page()

    def flow(self, text: str, size: float = 10, indent: float = 0.0,
             color: HexColor = _TEXT, leading: float | None = None,
             align: str = "left") -> None:
        """流式段落：自动换行、自动分页。"""
        leading = leading if leading is not None else size + 5
        for segment in _wrap(str(text), self.font, size, _CONTENT_W - indent):
            self.ensure(leading)
            c = self.c
            c.setFont(self.font, size)
            c.setFillColor(color)
            if align == "right":
                c.drawRightString(_PAGE_W - _MARGIN - indent, self.y - size, segment)
            elif align == "center":
                c.drawCentredString(_MARGIN + _CONTENT_W / 2, self.y - size, segment)
            else:
                c.drawString(_MARGIN + indent, self.y - size, segment)
            self.y -= leading


def _section(book: _Book, text: str) -> None:
    """章标题：主色方块 + 标题 + 细线。"""
    book.ensure(40)
    c = book.c
    y = book.y
    c.setFillColor(_PRIMARY)
    c.rect(_MARGIN, y - 13, 6, 17, fill=1, stroke=0)
    c.setFont(book.font, 15)
    c.setFillColor(_TEXT)
    c.drawString(_MARGIN + 14, y - 11, text)
    try:
        text_w = pdfmetrics.stringWidth(text, book.font, 15)
    except Exception:  # noqa: BLE001
        text_w = len(text) * 15
    c.setStrokeColor(_LINE)
    c.setLineWidth(0.8)
    c.line(_MARGIN + 18 + text_w, y - 17, _MARGIN + _CONTENT_W, y - 17)
    book.y = y - 36


def _sub(book: _Book, text: str) -> None:
    """小节标题：深主色文字。"""
    book.ensure(24)
    c = book.c
    c.setFont(book.font, 11.5)
    c.setFillColor(_PRIMARY_DARK)
    c.drawString(_MARGIN, book.y - 11, text)
    book.y -= 28


# ------------------------------------------------------------------ 封面
def _draw_cover(c: canvas.Canvas, font: str, trip: dict, days: list[dict],
                places: list[dict], bookings: list[dict], transports: list[dict]) -> None:
    w, h = _PAGE_W, _PAGE_H
    # 顶部品牌色块 + 浅色点缀条
    c.setFillColor(_PRIMARY)
    c.rect(0, h - 132, w, 132, fill=1, stroke=0)
    c.setFillColor(_ACCENT)
    c.rect(0, h - 136, w, 4, fill=1, stroke=0)
    c.setFillColor(_WHITE)
    c.setFont(font, 15)
    c.drawString(_MARGIN, h - 62, "瞬旅 FlashTrip")
    c.setFillColor(_SOFT)
    c.setFont(font, 9)
    c.drawString(_MARGIN, h - 82, "TRIP BOOKLET · 行程手册")
    # 标题（超长自动降字号，最多两行）
    title = _trip_title(trip)
    size, lines = 26, _wrap(title, font, 26, _CONTENT_W - 24)
    if len(lines) > 2:
        size, lines = 18, _wrap(title, font, 18, _CONTENT_W - 24)
    c.setFillColor(_TEXT)
    c.setFont(font, size)
    y = h - 200
    for line in lines:
        c.drawString(_MARGIN, y, line)
        y -= size + 10
    c.setFillColor(_PRIMARY)
    c.rect(_MARGIN, y + 2, 64, 3, fill=1, stroke=0)
    y -= 30
    # 目的地
    dest = str(trip.get("destination") or "").strip()
    if dest:
        c.setFont(font, 13)
        c.setFillColor(_PRIMARY_DARK)
        c.drawString(_MARGIN, y, _ellipsize(dest, font, 13, _CONTENT_W))
        y -= 26
    # 元信息（标签 + 值）
    rows: list[tuple[str, str]] = []
    date_range = _trip_date_range(trip)
    if date_range:
        rows.append(("出行日期", date_range))
    if days:
        rows.append(("行程天数", f"{len(days)} 天"))
    people = _cover_people(trip)
    if people:
        rows.append(("出行人数", people))
    if trip.get("currency"):
        rows.append(("结算币种", str(trip["currency"])))
    y = min(y, 500)
    for label, value in rows:
        c.setFont(font, 9.5)
        c.setFillColor(_MUTED)
        c.drawString(_MARGIN, y, label)
        c.setFont(font, 11)
        c.setFillColor(_TEXT)
        vlines = _wrap(value, font, 11, _CONTENT_W - 96)
        extra = 0
        for vline in vlines:
            c.drawString(_MARGIN + 96, y - extra, vline)
            extra += 16
        y -= 24 + extra
    # 统计条（数字 + 标签 + 分隔线）
    stats = [(str(len(days)), "天"), (str(len(places)), "个地点"),
             (str(len(bookings)), "条预订"), (str(len(transports)), "段交通")]
    slot = _CONTENT_W / 4
    for i, (num, label) in enumerate(stats):
        cx = _MARGIN + slot * i + slot / 2
        c.setFont(font, 21)
        c.setFillColor(_PRIMARY_DARK)
        c.drawCentredString(cx, 186, num)
        c.setFont(font, 9)
        c.setFillColor(_MUTED)
        c.drawCentredString(cx, 166, label)
        if i:
            c.setStrokeColor(_LINE)
            c.setLineWidth(0.7)
            c.line(_MARGIN + slot * i, 158, _MARGIN + slot * i, 204)
    # 生成时间与底部色带
    c.setFont(font, 8.5)
    c.setFillColor(_MUTED)
    c.drawRightString(w - _MARGIN, 42, f"生成于 {datetime.now():%Y-%m-%d %H:%M} · 瞬旅 FlashTrip")
    c.setFillColor(_ACCENT)
    c.rect(0, 21, w, 3, fill=1, stroke=0)
    c.setFillColor(_PRIMARY)
    c.rect(0, 0, w, 21, fill=1, stroke=0)


# ------------------------------------------------------------------ 总览
def _draw_overview(book: _Book, trip: dict, days: list[dict], places: list[dict],
                   bookings: list[dict], transports: list[dict], expenses: list[dict]) -> None:
    _section(book, "行程总览")
    book.flow(
        f"共 {len(days)} 天 · {len(places)} 个地点 · {len(bookings)} 条预订 · {len(transports)} 段交通",
        size=10, color=_MUTED,
    )
    book.gap(6)
    if days:
        _sub(book, "每日安排速览")
        grouped = _group_by(places, "day_id")
        for day in days:
            items = grouped.get(str(day.get("id") or ""), [])
            titles = " → ".join(str(p.get("title") or "地点") for p in items[:3])
            if len(items) > 3:
                titles += f" 等 {len(items)} 个地点"
            summary = titles or str(day.get("title") or "（无安排）")
            prefix = f"D{day.get('day_index') or '?'}"
            when = _fmt_md(day.get("date"))
            if when:
                prefix += f" · {when}"
            weekday = _weekday_cn(day.get("date"))
            if weekday:
                prefix += f" {weekday}"
            book.flow(f"{prefix}　{summary}", size=9.5, indent=6)
    else:
        book.flow("（暂无日程安排）", size=9.5, color=_MUTED)
    # 预算概览（仅当导出数据含预算字段时渲染）
    budget = _num(trip.get("budget")) or _num(trip.get("budget_total")) or _num(trip.get("total_budget"))
    if budget is not None:
        _sub(book, "预算概览")
        spent = sum(_num(e.get("amount")) or 0.0 for e in expenses)
        currency = str(trip.get("currency") or _expense_currency(expenses) or "").strip()
        remain = budget - spent
        book.flow(
            f"预算 {_fmt_amount(budget)} {currency} · 已花费 {_fmt_amount(spent)} {currency} "
            f"· 剩余 {_fmt_amount(remain)} {currency}",
            size=10,
        )
        book.ensure(20)
        c = book.c
        y = book.y
        c.setFillColor(_LINE)
        c.rect(_MARGIN, y - 14, _CONTENT_W, 6, fill=1, stroke=0)
        if budget > 0 and spent > 0:
            share = min(spent / budget, 1.0)
            c.setFillColor(_PRIMARY)
            c.rect(_MARGIN, y - 14, max(4.0, _CONTENT_W * share), 6, fill=1, stroke=0)
        book.y = y - 24


# ------------------------------------------------------------------ 分日行程
def _draw_day_bar(book: _Book, day: dict, count: int) -> None:
    bar_h = 26
    book.ensure(bar_h + 16)
    c = book.c
    y = book.y - bar_h
    c.setFillColor(_PRIMARY)
    c.roundRect(_MARGIN, y, _CONTENT_W, bar_h, 4, fill=1, stroke=0)
    label = f"第 {day.get('day_index') or '?'} 天"
    when = _fmt_day(day.get("date"))
    if when:
        label += f" · {when}"
    weekday = _weekday_cn(day.get("date"))
    if weekday:
        label += f" {weekday}"
    if day.get("title"):
        label += f" · {str(day['title']).strip()}"
    c.setFillColor(_WHITE)
    c.setFont(book.font, 12)
    c.drawString(_MARGIN + 12, y + 8, _ellipsize(label, book.font, 12, _CONTENT_W - 130))
    if count:
        c.setFont(book.font, 9)
        c.drawRightString(_MARGIN + _CONTENT_W - 12, y + 9, f"{count} 个地点")
    book.y = y - 12


def _draw_place_card(book: _Book, item: dict) -> None:
    """地点卡片：左列时间，右侧名称/地址/备注，右上角时长。整卡不跨页。"""
    font = book.font
    title = str(item.get("title") or item.get("name") or item.get("type") or "地点").strip()
    start, end = _fmt_hm(item.get("start_time")), _fmt_hm(item.get("end_time"))
    time_lines = [start, end] if start and end else ([start or end] if (start or end) else [])
    address = str(item.get("address") or "").strip()
    note = str(item.get("note") or "").strip()
    duration = _fmt_duration(item.get("duration_min"))
    pad = 10.0
    body_x = _MARGIN + 92
    dur_w = 88 if duration else 0
    body_w = _CONTENT_W - 92 - 14 - dur_w
    title_lines = _wrap(title, font, 11.5, body_w)
    addr_lines = _wrap(address, font, 8.8, body_w) if address else []
    note_lines = _wrap(f"备注：{note}", font, 8.8, body_w) if note else []
    height = pad * 2 + max(16, len(title_lines) * 15) + len(addr_lines) * 11.5 + len(note_lines) * 11.5
    height = max(height, pad * 2 + len(time_lines) * 12 + 6, 36)
    book.ensure(height + 10)
    c = book.c
    top = book.y
    c.setFillColor(_CARD)
    c.roundRect(_MARGIN, top - height, _CONTENT_W, height, 5, fill=1, stroke=0)
    c.setFillColor(_PRIMARY)
    c.rect(_MARGIN, top - height, 3, height, fill=1, stroke=0)
    # 左列时间（起止各一行）
    if time_lines:
        c.setFont(font, 9)
        c.setFillColor(_PRIMARY_DARK)
        for i, line in enumerate(time_lines):
            c.drawString(_MARGIN + 12, top - pad - 9 - i * 12, line)
    # 名称
    c.setFont(font, 11.5)
    c.setFillColor(_TEXT)
    for i, line in enumerate(title_lines):
        c.drawString(body_x, top - pad - 11 - i * 15, line)
    # 时长（右上角）
    if duration:
        c.setFont(font, 8.8)
        c.setFillColor(_PRIMARY_DARK)
        c.drawRightString(_MARGIN + _CONTENT_W - 14, top - pad - 10, duration)
    # 地址与备注
    c.setFont(font, 8.8)
    c.setFillColor(_MUTED)
    yy = top - pad - 11 - (len(title_lines) - 1) * 15 - 14
    for line in addr_lines:
        c.drawString(body_x, yy, line)
        yy -= 11.5
    for line in note_lines:
        c.drawString(body_x, yy, line)
        yy -= 11.5
    book.y = top - height - 10


def _draw_day_total(book: _Book, day_expenses: list[dict]) -> None:
    total = sum(_num(e.get("amount")) or 0.0 for e in day_expenses)
    currency = _expense_currency(day_expenses)
    amount_text = f"{_fmt_amount(total)} {currency}".strip()
    book.ensure(30)
    c = book.c
    y = book.y
    c.setStrokeColor(_LINE)
    c.setLineWidth(0.7)
    c.line(_MARGIN + _CONTENT_W * 0.35, y - 6, _MARGIN + _CONTENT_W, y - 6)
    c.setFont(book.font, 9.5)
    c.setFillColor(_MUTED)
    c.drawString(_MARGIN + _CONTENT_W * 0.35, y - 20, f"当日小计（{len(day_expenses)} 笔）")
    c.setFont(book.font, 10.5)
    c.setFillColor(_PRIMARY_DARK)
    c.drawRightString(_MARGIN + _CONTENT_W, y - 20, amount_text)
    book.y = y - 34


def _draw_daily(book: _Book, days: list[dict], places: list[dict],
                transports: list[dict], expenses: list[dict]) -> None:
    _section(book, "分日行程")
    place_grouped = _group_by(places, "day_id")
    transport_grouped = _group_by(transports, "day_id")
    expense_grouped = _group_by(expenses, "day_id")
    if not days:
        if places:
            _sub(book, "全程安排（未设置日程）")
            for item in _sorted_by_time(places, "start_time"):
                _draw_place_card(book, item)
        else:
            book.flow("（暂无行程安排）", size=9.5, color=_MUTED)
        return
    for day in days:
        day_id = str(day.get("id") or "")
        items = _sorted_by_time(place_grouped.get(day_id, []), "start_time")
        day_transports = _sorted_by_time(transport_grouped.get(day_id, []), "depart_at")
        day_expenses = expense_grouped.get(day_id, [])
        book.ensure(26 + 50)  # 标题条与首张卡片同页，避免孤儿标题
        _draw_day_bar(book, day, len(items))
        note = str(day.get("note") or "").strip()
        if note:
            book.flow(f"备注：{note}", size=9, indent=12, color=_MUTED)
        if not items and not day_transports:
            book.flow("（当日暂无安排）", size=9.5, indent=12, color=_MUTED)
        for item in items:
            _draw_place_card(book, item)
        if day_transports:
            _sub(book, "当日交通")
            for t in day_transports:
                line = (
                    f"{_label(_MODE_LABELS, t.get('mode'))} · "
                    f"{t.get('from_name') or '—'} → {t.get('to_name') or '—'}"
                )
                depart, arrive = _fmt_hm(t.get("depart_at")), _fmt_hm(t.get("arrive_at"))
                if depart or arrive:
                    line += f" · {depart or '--:--'} – {arrive or '--:--'}"
                if t.get("carrier"):
                    line += f" · {str(t['carrier']).strip()}"
                book.flow(line, size=9.5, indent=12)
        if day_expenses:
            _draw_day_total(book, day_expenses)
        book.gap(18)
    pool = [p for p in places if not p.get("day_id")]
    if pool:
        book.gap(6)
        _sub(book, "待规划地点")
        for item in _sorted_by_time(pool, "start_time"):
            _draw_place_card(book, item)


# ------------------------------------------------------------------ 表格
def _table(book: _Book, columns: list[tuple[str, float, str]], rows: list[list[str]],
           row_extra=None) -> None:
    """手绘表格：columns 为 (表头, 列宽, 对齐)，行内自动换行、整行换页后重画表头。

    row_extra(c, row_bottom_y, row_height, row_index) 可在每行追加装饰（如占比条）。
    """
    font = book.font

    def draw_header() -> None:
        book.ensure(26)
        y = book.y
        book.c.setFont(font, 9)
        book.c.setFillColor(_PRIMARY_DARK)
        x = _MARGIN
        for title, width, align in columns:
            if align == "right":
                book.c.drawRightString(x + width, y, title)
            elif align == "center":
                book.c.drawCentredString(x + width / 2, y, title)
            else:
                book.c.drawString(x, y, title)
            x += width
        book.c.setStrokeColor(_LINE)
        book.c.setLineWidth(0.8)
        book.c.line(_MARGIN, y - 7, _MARGIN + _CONTENT_W, y - 7)
        book.y = y - 20

    if not rows:
        return
    draw_header()
    for row_index, row in enumerate(rows):
        cells = [_wrap(str(cell), font, 9, width - 8) for cell, (_, width, _) in zip(row, columns, strict=False)]
        row_h = max(len(seg) for seg in cells) * 11 + 7
        if book.y - row_h < _BOTTOM:
            book.break_page()
            draw_header()
        y = book.y
        x = _MARGIN
        book.c.setFont(font, 9)
        book.c.setFillColor(_TEXT)
        for (_, width, align), segments in zip(columns, cells, strict=False):
            for i, line in enumerate(segments):
                yy = y - 11 - i * 11
                if align == "right":
                    book.c.drawRightString(x + width, yy, line)
                elif align == "center":
                    book.c.drawCentredString(x + width / 2, yy, line)
                else:
                    book.c.drawString(x, yy, line)
            x += width
        book.c.setStrokeColor(_LINE)
        book.c.setLineWidth(0.5)
        book.c.line(_MARGIN, y - row_h + 3, _MARGIN + _CONTENT_W, y - row_h + 3)
        if row_extra is not None:
            row_extra(book.c, y - row_h, row_h, row_index)
        book.y = y - row_h


def _draw_lists(book: _Book, bookings: list[dict], transports: list[dict]) -> None:
    _section(book, "预订与交通")
    _sub(book, "预订")
    if not bookings:
        book.flow("（暂无预订记录）", size=9.5, color=_MUTED)
    else:
        columns = [("名称", 122, "left"), ("类型", 46, "center"), ("时间", 102, "left"),
                   ("确认号", 96, "left"), ("金额", 133, "right")]
        rows = []
        for b in _sorted_by_time(bookings, "start_at"):
            amount = _num(b.get("amount"))
            rows.append([
                str(b.get("vendor") or "").strip() or _label(_BOOKING_TYPE_LABELS, b.get("type")),
                _label(_BOOKING_TYPE_LABELS, b.get("type")),
                _fmt_dhm(b.get("start_at")) or "—",
                str(b.get("booking_no") or "").strip() or "—",
                "—" if amount is None else f"{_fmt_amount(amount)} {str(b.get('currency') or '').strip()}".strip(),
            ])
        _table(book, columns, rows)
    book.gap(16)
    _sub(book, "交通")
    if not transports:
        book.flow("（暂无交通记录）", size=9.5, color=_MUTED)
    else:
        columns = [("方式", 50, "center"), ("行程", 200, "left"),
                   ("时间", 152, "left"), ("承运 / 班次", 97, "left")]
        rows = []
        for t in _sorted_by_time(transports, "depart_at"):
            depart, arrive = _fmt_dhm(t.get("depart_at")), _fmt_dhm(t.get("arrive_at"))
            when = " → ".join(v for v in (depart, arrive) if v) or "—"
            carrier = " · ".join(
                v for v in (str(t.get("carrier") or "").strip(), str(t.get("seat") or "").strip()) if v
            )
            rows.append([
                _label(_MODE_LABELS, t.get("mode")),
                f"{t.get('from_name') or '—'} → {t.get('to_name') or '—'}",
                when,
                carrier or "—",
            ])
        _table(book, columns, rows)


# ------------------------------------------------------------------ 费用汇总
def _draw_expense_summary(book: _Book, trip: dict, expenses: list[dict]) -> None:
    _section(book, "费用汇总")
    if not expenses:
        book.flow("（暂无费用记录）", size=9.5, color=_MUTED)
        return
    sums: dict[str, float] = {}
    counts: dict[str, int] = {}
    for item in expenses:
        category = str(item.get("category") or "other")
        sums[category] = sums.get(category, 0.0) + (_num(item.get("amount")) or 0.0)
        counts[category] = counts.get(category, 0) + 1
    total = sum(sums.values())
    currency = str(trip.get("currency") or _expense_currency(expenses) or "").strip()
    ordered = sorted(sums.items(), key=lambda kv: kv[1], reverse=True)
    columns = [("分类", 120, "left"), ("笔数", 66, "center"), ("金额", 130, "right"), ("占比", 183, "left")]
    rows = []
    shares: list[float] = []
    for category, value in ordered:
        rows.append([
            _label(_CATEGORY_LABELS, category),
            str(counts[category]),
            f"{_fmt_amount(value)} {currency}".strip(),
        ])
        shares.append(0.0 if total <= 0 else value / total)

    def draw_share_bar(c: canvas.Canvas, row_bottom: float, row_h: float, index: int) -> None:
        """占比列内的水平条：灰底 + 主色按份额填充。"""
        bar_x = _MARGIN + 120 + 66 + 130 + 6
        bar_w = 183 - 14
        bar_y = row_bottom + row_h / 2 - 2.5
        c.setFillColor(_LINE)
        c.rect(bar_x, bar_y, bar_w, 5, fill=1, stroke=0)
        if shares[index] > 0:
            c.setFillColor(_PRIMARY)
            c.rect(bar_x, bar_y, max(2.0, bar_w * shares[index]), 5, fill=1, stroke=0)

    _table(book, columns, rows, row_extra=draw_share_bar)
    book.gap(8)
    book.ensure(32)
    c = book.c
    y = book.y
    c.setStrokeColor(_PRIMARY_DARK)
    c.setLineWidth(1.1)
    c.line(_MARGIN, y - 6, _MARGIN + _CONTENT_W, y - 6)
    c.setFont(book.font, 11)
    c.setFillColor(_TEXT)
    c.drawString(_MARGIN, y - 22, "总计")
    c.setFillColor(_PRIMARY_DARK)
    c.drawRightString(_MARGIN + _CONTENT_W, y - 22, f"{_fmt_amount(total)} {currency}".strip())
    book.y = y - 36
    currencies = {str(e.get("currency") or "").strip() for e in expenses if e.get("currency")}
    if len(currencies) > 1:
        book.flow("注：记录中存在多种币种，合计未做汇率换算，仅供参考。", size=8.5, color=_MUTED)


# ------------------------------------------------------------------ 组装
def build_pdf(*, trip: dict | None = None, days: list[dict] | None = None,
              places: list[dict] | None = None, bookings: list[dict] | None = None,
              expenses: list[dict] | None = None,
              transports: list[dict] | None = None) -> bytes:
    """生成 PDF：封面 / 行程总览 / 分日行程 / 预订与交通 / 费用汇总。"""
    trip = trip or {}
    days, places = days or [], places or []
    bookings, expenses = bookings or [], expenses or []
    transports = transports or []
    font = _register_font()
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, pageCompression=1)
    title = _trip_title(trip)
    c.setTitle(f"瞬旅 FlashTrip · {title}")
    c.setAuthor("FlashTrip")
    c.setSubject("行程手册")
    book = _Book(c, font, title)
    _draw_cover(c, font, trip, days, places, bookings, transports)
    book.break_page()
    _draw_overview(book, trip, days, places, bookings, transports, expenses)
    book.gap(10)
    _draw_daily(book, days, places, transports, expenses)
    book.gap(10)
    _draw_lists(book, bookings, transports)
    book.gap(10)
    _draw_expense_summary(book, trip, expenses)
    book.finish()
    c.save()
    return buf.getvalue()


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
