"""导出：中文 PDF 非空（CID 字体免打包）、ICS VEVENT 为 UTC 时间、无表时优雅降级。"""
from __future__ import annotations

from datetime import datetime, timezone

from app.services.export_service import build_ics, build_pdf, render_trip_ics, render_trip_pdf

TRIP = {
    "title": "东京五日游",
    "currency": "JPY",
    "start_date": "2026-05-01",
    "end_date": "2026-05-05",
}


def test_pdf_non_empty_with_chinese_content():
    data = build_pdf(
        trip=TRIP,
        days=[{"id": "d1", "day_index": 1, "date": "2026-05-01"}],
        places=[{"id": "p1", "day_id": "d1", "title": "浅草寺", "address": "东京都台东区",
                 "lng": 139.7967, "lat": 35.7148, "coord_system": "WGS84"}],
        bookings=[{"id": "b1", "type": "flight", "vendor": "全日空", "booking_no": "NH962",
                   "start_at": "2026-05-01T09:00:00+00:00", "amount": 3200, "currency": "CNY"}],
        expenses=[{"id": "e1", "category": "food", "amount": 120.5, "currency": "JPY"}],
        transports=[{"id": "t1", "mode": "train", "from_name": "成田", "to_name": "市区",
                     "depart_at": "2026-05-01T10:30:00+00:00"}],
    )
    assert isinstance(data, bytes)
    assert len(data) > 800
    assert data.startswith(b"%PDF")
    assert b"%%EOF" in data


def test_pdf_cjk_font_needs_no_bundled_font_file():
    """仅用 reportlab 内置 STSong-Light，标题含中文也应正常生成。"""
    data = build_pdf(trip={"title": "中文行程册测试"})
    assert data.startswith(b"%PDF")
    assert len(data) > 500


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
