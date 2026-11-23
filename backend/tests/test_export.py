"""导出：中文 PDF 行程手册（CID 字体免打包）、页数结构、ICS UTC 时间、无表时优雅降级。"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from app.services.export_service import build_ics, build_pdf, render_trip_ics, render_trip_pdf

TRIP = {
    "title": "东京五日游",
    "destination": "东京",
    "currency": "JPY",
    "start_date": "2026-05-01",
    "end_date": "2026-05-05",
    "traveler_count": 4,
    "has_children": True,
    "children_count": 1,
}

DAYS = [
    {"id": "d1", "day_index": 1, "date": "2026-05-01"},
    {"id": "d2", "day_index": 2, "date": "2026-05-02"},
]

PLACES = [
    {"id": "p1", "day_id": "d1", "title": "浅草寺", "address": "东京都台东区",
     "start_time": "2026-05-01T09:00:00+00:00", "end_time": "2026-05-01T11:00:00+00:00",
     "duration_min": 120, "note": "雷门合影", "lng": 139.7967, "lat": 35.7148,
     "coord_system": "WGS84", "sort_key": "a0"},
    {"id": "p2", "day_id": "d1", "title": "上野公园", "address": "东京都台东区上野",
     "start_time": "2026-05-01T14:00:00+00:00", "duration_min": 90, "sort_key": "a1"},
    {"id": "p3", "day_id": "d2", "title": "东京塔", "address": "东京都港区", "sort_key": "b0"},
]

BOOKINGS = [
    {"id": "b1", "type": "flight", "vendor": "全日空", "booking_no": "NH962",
     "start_at": "2026-05-01T09:00:00+00:00", "amount": 3200, "currency": "CNY"},
    {"id": "b2", "type": "hotel", "vendor": "新宿王子酒店", "booking_no": "PRN-8821",
     "start_at": "2026-05-01T15:00:00+00:00", "amount": 88000, "currency": "JPY"},
]

EXPENSES = [
    {"id": "e1", "category": "food", "amount": 120.5, "currency": "JPY", "day_id": "d1"},
    {"id": "e2", "category": "transport", "amount": 200, "currency": "JPY", "day_id": "d1"},
    {"id": "e3", "category": "ticket", "amount": 3000, "currency": "JPY"},
]

TRANSPORTS = [
    {"id": "t1", "mode": "train", "from_name": "成田", "to_name": "市区",
     "depart_at": "2026-05-01T10:30:00+00:00", "arrive_at": "2026-05-01T12:00:00+00:00",
     "carrier": "N'EX", "day_id": "d1"},
]


def _pdf_pages(data: bytes) -> int:
    """reportlab 在页面树根写入 /Count N（正文对象不受流压缩影响）。"""
    counts = [int(v) for v in re.findall(rb"/Count\s+(\d+)", data)]
    return max(counts) if counts else 0


def test_pdf_full_booklet_structure():
    data = build_pdf(
        trip=TRIP, days=DAYS, places=PLACES, bookings=BOOKINGS,
        expenses=EXPENSES, transports=TRANSPORTS,
    )
    assert isinstance(data, bytes)
    assert len(data) > 2000
    assert data.startswith(b"%PDF")
    assert b"%%EOF" in data
    # 封面 / 总览 / 分日行程 / 预订与交通 / 费用汇总 → 多页成册
    assert _pdf_pages(data) >= 3
    # 文档元信息位于非压缩区，作者恒为 ASCII 可直接断言
    assert b"(FlashTrip)" in data


def test_pdf_large_trip_spans_multiple_pages():
    """10 天 × 每天多个地点：分日行程会跨页，页眉页脚逐页补齐。"""
    days = [{"id": f"d{i}", "day_index": i, "date": f"2026-05-{i:02d}"} for i in range(1, 11)]
    places = [
        {"id": f"p{i}-{j}", "day_id": f"d{i}", "title": f"地点 {i}-{j}",
         "address": f"地址 {i}-{j}", "note": "停留参观", "duration_min": 90}
        for i in range(1, 11) for j in range(4)
    ]
    data = build_pdf(trip=TRIP, days=days, places=places)
    assert data.startswith(b"%PDF")
    assert _pdf_pages(data) >= 6


def test_pdf_cjk_font_needs_no_bundled_font_file():
    """仅用 reportlab 内置 STSong-Light，标题含中文也应正常生成。"""
    data = build_pdf(trip={"title": "中文行程册测试"})
    assert data.startswith(b"%PDF")
    assert len(data) > 500
    # 只有封面 + 空数据各节：仍应有封面与其后内容页
    assert _pdf_pages(data) >= 2


def test_pdf_wraps_and_shrinks_long_text_without_error():
    """超长标题降字号、地址/备注换行、异常时长都不会让渲染中断。"""
    long_text = "超长文本内容" * 40
    place = {
        "id": "p1", "day_id": "d1", "title": long_text,
        "address": long_text, "note": long_text, "duration_min": 99999,
    }
    data = build_pdf(
        trip={"title": long_text, "destination": long_text},
        days=[{"id": "d1", "day_index": 1, "date": "2026-05-01"}],
        places=[place],
    )
    assert data.startswith(b"%PDF")
    assert _pdf_pages(data) >= 3


def test_pdf_budget_block_renders_when_present():
    """数据带预算字段时渲染预算块（含进度条），页数不少于无预算版本。"""
    kwargs = dict(trip=TRIP, days=DAYS, places=PLACES, expenses=EXPENSES)
    with_budget = build_pdf(trip={**TRIP, "budget": 20000}, **{k: v for k, v in kwargs.items() if k != "trip"})
    without_budget = build_pdf(**kwargs)
    assert with_budget.startswith(b"%PDF")
    assert _pdf_pages(with_budget) >= _pdf_pages(without_budget)


def test_ics_has_vevent_with_utc_times():
    data = build_ics([{
        "uid": "flight-1@flashtrip",
        "summary": "飞往东京",
        "start": datetime(2026, 5, 1, 8, 0, tzinfo=timezone.utc),
        "end": datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc),
        "description": "NH962",
    }])
    text = data.decode("utf-8")
    assert "BEGIN:VCALENDAR" in text
    assert "BEGIN:VEVENT" in text
    assert "END:VCALENDAR" in text
    assert "20260501T080000Z" in text
    assert "20260501T120000Z" in text


def test_ics_multiple_events_and_date_string_to_utc():
    events = [
        {"uid": "a@flashtrip", "summary": "出发", "start": "2026-06-01"},
        {"uid": "b@flashtrip", "summary": "返程", "start": "2026-06-05"},
        {"uid": "c@flashtrip", "summary": "全天", "start": "2026-06-03", "end": "2026-06-03"},
    ]
    data = build_ics(events, calendar_name="全部行程")
    text = data.decode("utf-8")
    assert text.count("BEGIN:VEVENT") == 3
    assert "20260601T000000Z" in text


class _FakeDB:
    """表尚未迁移/不可用时，渲染函数仍应产出合法文件。"""

    def query(self, model):
        raise RuntimeError("table missing")

    def get(self, model, key):
        raise RuntimeError("table missing")


def test_render_degrades_without_tables():
    pdf = render_trip_pdf(_FakeDB(), "trip-1")
    assert pdf.startswith(b"%PDF")
    ics = render_trip_ics(_FakeDB(), "trip-1", "trip")
    assert b"BEGIN:VCALENDAR" in ics
    assert b"BEGIN:VCALENDAR" in render_trip_ics(_FakeDB(), None, "all")
