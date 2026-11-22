"""天气服务契约：三家归一化结构一致、缓存命中、失败统一 2006、提示词。

所有网络调用通过 monkeypatch httpx.get，绝不发起真实请求。
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.errors import AppError, ErrorCode
from app.db.base import Base
from app.models.weather import WeatherCache
from app.services import weather_service as ws


class _Resp:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


_UAPIS = {
    "weather": "晴", "temperature": "26", "humidity": "60",
    "wind_direction": "东南风", "wind_power": "3级", "report_time": "2026-11-23 10:00",
    "alerts": [{"title": "大风蓝色预警"}],
    "forecast": [{
        "date": "2026-11-23", "week": "周一", "weather_day": "晴", "weather_night": "多云",
        "temp_max": "28", "temp_min": "18", "wind_dir_day": "东南风", "pop": "0.1", "uv_index": "7",
    }],
}

_AMAP = {
    "status": "1",
    "lives": [{
        "weather": "晴", "temperature": "26", "humidity": "60",
        "winddirection": "东南", "windpower": "3", "reporttime": "2026-11-23 10:00",
    }],
    "forecasts": [{"casts": [{
        "date": "2026-11-23", "week": "1", "dayweather": "晴", "nightweather": "多云",
        "daytemp": "28", "nighttemp": "18", "daywind": "东南",
    }]}],
}

_QW_DAILY = {"code": "200", "daily": [{
    "fxDate": "2026-11-23", "textDay": "晴", "textNight": "多云",
    "tempMax": "28", "tempMin": "18", "windDirDay": "东南", "pop": "0.1", "uvIndex": "7",
}]}
_QW_NOW = {"code": "200", "now": {
    "text": "晴", "temp": "26", "humidity": "60",
    "windDir": "东南风", "windScale": "3", "obsTime": "2026-11-23T10:00+08:00",
}}


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine, tables=[WeatherCache.__table__])
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    yield session
    session.close()
    engine.dispose()


def _fake_get(monkeypatch):
    def fake(url, *, params=None, headers=None, timeout=None):
        assert timeout == 8.0
        if "uapis.cn" in url:
            return _Resp(_UAPIS)
        if "restapi.amap.com" in url:
            return _Resp(_AMAP)
        if "devapi.qweather.com" in url and "/7d" in url:
            return _Resp(_QW_DAILY)
        if "devapi.qweather.com" in url and "/now" in url:
            return _Resp(_QW_NOW)
        raise AssertionError(f"未预期的上游地址：{url}")

    monkeypatch.setattr(ws.httpx, "get", fake)


_CURRENT_KEYS = {"weather", "temperature", "humidity", "wind", "report_time", "alerts"}
_FORECAST_KEYS = {
    "date", "week", "weather_day", "weather_night",
    "temp_max", "temp_min", "wind", "pop", "uv",
}


@pytest.mark.parametrize("provider", ws.PROVIDERS)
def test_all_providers_normalize_identically(monkeypatch, db, provider):
    _fake_get(monkeypatch)
    data = ws.fetch_weather("苏州", days=3, provider=provider, db=db)
    assert set(data) == {"provider", "city", "current", "forecast", "advice_hints", "cached"}
    assert data["provider"] == provider and data["city"] == "苏州"
    assert set(data["current"]) == _CURRENT_KEYS
    assert isinstance(data["current"]["temperature"], float)
    assert isinstance(data["current"]["humidity"], int)
    assert isinstance(data["current"]["alerts"], list)
    assert data["forecast"] and set(data["forecast"][0]) == _FORECAST_KEYS
    assert isinstance(data["forecast"][0]["temp_max"], float)
    assert isinstance(data["forecast"][0]["pop"], float)
    assert isinstance(data["advice_hints"], list) and data["advice_hints"]
    assert data["cached"] is False


def test_cache_hit_returns_cached_true(monkeypatch, db):
    _fake_get(monkeypatch)
    first = ws.fetch_weather("苏州", days=3, provider="uapis", db=db)
    assert first["cached"] is False

    def _should_not_call(*args, **kwargs):
        pytest.fail("缓存命中后不应再次请求上游")

    monkeypatch.setattr(ws.httpx, "get", _should_not_call)
    second = ws.fetch_weather("苏州", days=3, provider="uapis", db=db)
    assert second["cached"] is True
    assert second["current"] == first["current"]


def test_provider_failure_raises_2006(monkeypatch, db):
    def boom(*args, **kwargs):
        raise OSError("network down")

    monkeypatch.setattr(ws.httpx, "get", boom)
    with pytest.raises(AppError) as exc:
        ws.fetch_weather("苏州", provider="uapis", db=db)
    assert exc.value.code == ErrorCode.MAP_PROVIDER_ERROR
    assert "天气服务暂不可用" in exc.value.message


def test_invalid_provider_rejected(monkeypatch, db):
    with pytest.raises(AppError) as exc:
        ws.fetch_weather("苏州", provider="unknown", db=db)
    assert exc.value.code == ErrorCode.MAP_PROVIDER_ERROR


def test_build_advice_prompt_contains_trip_and_weather():
    trip = {
        "title": "苏州三日游", "destination": "苏州",
        "start_date": "2026-11-25", "end_date": "2026-11-27",
        "traveler_count": 3, "children_count": 1,
    }
    weather = {
        "current": {"weather": "晴", "temperature": 26.0},
        "forecast": [], "advice_hints": ["注意防晒"],
    }
    prompt = ws.build_advice_prompt(trip, weather)
    assert "苏州三日游" in prompt and "2026-11-25" in prompt
    assert "3 人" in prompt and "注意防晒" in prompt
