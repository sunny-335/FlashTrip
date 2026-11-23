"""天气服务契约：三家归一化、和风 Host+GeoAPI、高德 adcode+base/all、缓存质量门禁。

所有网络调用通过 monkeypatch httpx.get 拦截，绝不发起真实请求。
"""
from __future__ import annotations

import json
from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import config_store as cs
from app.core.config_store import ConfigStore
from app.core.errors import AppError, ErrorCode
from app.db.base import Base
from app.models.weather import WeatherCache
from app.services import weather_service as ws

QW_HOST = "abc123.re.qweatherapi.com"

_UAPIS = {
    "weather": "晴", "temperature": "26", "humidity": "60",
    "wind_direction": "东南风", "wind_power": "3级", "report_time": "2026-11-23 10:00",
    "alerts": [{"title": "大风蓝色预警"}],
    "forecast": [{
        "date": "2026-11-23", "week": "周一", "weather_day": "晴", "weather_night": "多云",
        "temp_max": "28", "temp_min": "18", "wind_dir_day": "东南风", "pop": "0.1", "uv_index": "7",
    }],
}

_AMAP_DISTRICT = {"status": "1", "districts": [{"adcode": "320505", "name": "苏州"}]}

_AMAP_LIVE = {
    "status": "1",
    "lives": [{
        "weather": "晴", "temperature": "26", "humidity": "60",
        "winddirection": "东南", "windpower": "3", "reporttime": "2026-11-23 10:00",
    }],
}
_AMAP_LIVE_EMPTY = {"status": "1", "lives": []}

_AMAP_FORECAST = {
    "status": "1",
    "forecasts": [{"casts": [{
        "date": "2026-11-23", "week": "1", "dayweather": "晴", "nightweather": "多云",
        "daytemp": "28", "nighttemp": "18", "daywind": "东南",
    }]}],
}

_QW_GEO = {"code": "200", "location": [{"id": "101190401", "name": "苏州"}]}
_QW_DAILY = {"code": "200", "daily": [{
    "fxDate": "2026-11-23", "textDay": "晴", "textNight": "多云",
    "tempMax": "28", "tempMin": "18", "windDirDay": "东南", "pop": "0.1", "uvIndex": "7",
}]}
_QW_NOW = {"code": "200", "now": {
    "text": "晴", "temp": "26", "humidity": "60",
    "windDir": "东南风", "windScale": "3", "obsTime": "2026-11-23T10:00+08:00",
}}


class _Resp:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


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


def _cfg(**over) -> dict:
    cfg = dict(ws._WEATHER_DEFAULTS)
    cfg.update({
        "provider": "uapis",
        "amap_key_enc": ws.encrypt("amap-key"),
        "qweather_key_enc": ws.encrypt("qw-key"),
        "qweather_host": QW_HOST,
        "uapi_key_enc": "",
    })
    cfg.update(over)
    return cfg


def _install_cfg(monkeypatch, **over) -> dict:
    cfg = _cfg(**over)
    monkeypatch.setattr(ws, "_raw_weather_config", lambda: cfg)
    return cfg


def _fake_get(monkeypatch, *, live=None, qw_now=None, calls=None):
    def fake(url, *, params=None, headers=None, timeout=None):
        assert timeout == 8.0
        if calls is not None:
            calls.append({"url": url, "params": dict(params or {}), "headers": dict(headers or {})})
        if "uapis.cn" in url:
            return _Resp(_UAPIS)
        if "restapi.amap.com/v3/config/district" in url:
            return _Resp(_AMAP_DISTRICT)
        if "restapi.amap.com/v3/weather/weatherInfo" in url:
            ext = (params or {}).get("extensions")
            return _Resp(live if (ext == "base" and live is not None) else
                         (_AMAP_LIVE if ext == "base" else _AMAP_FORECAST))
        if "geoapi.qweather.com" in url:
            return _Resp(_QW_GEO)
        if QW_HOST in url and "/v7/weather/now" in url:
            return _Resp(qw_now if qw_now is not None else _QW_NOW)
        if QW_HOST in url and "/v7/weather/7d" in url:
            return _Resp(_QW_DAILY)
        raise AssertionError(f"未预期的上游地址：{url}")

    monkeypatch.setattr(ws.httpx, "get", fake)


_CURRENT_KEYS = {"weather", "temperature", "humidity", "wind", "report_time", "alerts"}
_FORECAST_KEYS = {
    "date", "week", "weather_day", "weather_night",
    "temp_max", "temp_min", "wind", "pop", "uv",
}


@pytest.mark.parametrize("provider", ws.PROVIDERS)
def test_all_providers_normalize_identically(monkeypatch, db, provider):
    _install_cfg(monkeypatch, provider=provider)
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


def test_qweather_uses_account_host_and_geolookup(monkeypatch, db):
    _install_cfg(monkeypatch, provider="qweather")
    calls: list[dict] = []
    _fake_get(monkeypatch, calls=calls)
    data = ws.fetch_weather("苏州", days=3, provider="qweather", db=db)
    assert data["current"]["temperature"] == 26.0

    geo = [c for c in calls if "geoapi.qweather.com" in c["url"]]
    assert geo, "应先经 GeoAPI 把城市名换成 LocationID"
    assert geo[0]["params"].get("location") == "苏州"
    assert geo[0]["params"].get("key") == "qw-key"

    now = [c for c in calls if "/v7/weather/now" in c["url"]]
    daily = [c for c in calls if "/v7/weather/7d" in c["url"]]
    assert now and daily
    for call in (now[0], daily[0]):
        assert QW_HOST in call["url"]
        assert "devapi.qweather.com" not in call["url"]
        assert call["headers"].get("X-QW-Api-Key") == "qw-key"
        assert call["params"].get("location") == "101190401"


def test_qweather_missing_host_gives_guidance(monkeypatch, db):
    _install_cfg(monkeypatch, provider="qweather", qweather_host="")
    _fake_get(monkeypatch)
    with pytest.raises(AppError) as exc:
        ws.fetch_weather("苏州", provider="qweather", db=db)
    assert exc.value.code == ErrorCode.WEATHER_CONFIG_MISSING
    assert "Host" in exc.value.message and "设置" in exc.value.message


def test_qweather_upstream_code_surfaces_reason(monkeypatch, db):
    _install_cfg(monkeypatch, provider="qweather")
    _fake_get(monkeypatch, qw_now={"code": "401"})
    with pytest.raises(AppError) as exc:
        ws.fetch_weather("苏州", provider="qweather", db=db)
    assert exc.value.code == ErrorCode.MAP_PROVIDER_ERROR
    assert "401" in exc.value.message and "认证" in exc.value.message


def test_amap_uses_adcode_and_separates_base_all(monkeypatch, db):
    _install_cfg(monkeypatch, provider="amap")
    calls: list[dict] = []
    _fake_get(monkeypatch, calls=calls)
    data = ws.fetch_weather("苏州", provider="amap", db=db)
    assert data["current"]["weather"] == "晴"
    assert data["current"]["temperature"] == 26.0

    district = [c for c in calls if "config/district" in c["url"]]
    assert district and district[0]["params"].get("keywords") == "苏州"

    weather_calls = [c for c in calls if "weatherInfo" in c["url"]]
    exts = sorted(c["params"].get("extensions") for c in weather_calls)
    assert exts == ["all", "base"], "实况与预报必须分别用 base / all 请求"
    assert all(c["params"].get("city") == "320505" for c in weather_calls)


def test_amap_adcode_fallback_to_city_name(monkeypatch, db):
    _install_cfg(monkeypatch, provider="amap")
    calls: list[dict] = []

    def fake(url, *, params=None, headers=None, timeout=None):
        calls.append({"url": url, "params": dict(params or {})})
        if "config/district" in url:
            return _Resp({"status": "1", "districts": []})  # 无 adcode -> 降级
        if "weatherInfo" in url:
            ext = (params or {}).get("extensions")
            return _Resp(_AMAP_LIVE if ext == "base" else _AMAP_FORECAST)
        raise AssertionError(url)

    monkeypatch.setattr(ws.httpx, "get", fake)
    data = ws.fetch_weather("苏州", provider="amap", db=db)
    assert data["current"]["temperature"] == 26.0
    weather_calls = [c for c in calls if "weatherInfo" in c["url"]]
    assert weather_calls and all(c["params"].get("city") == "苏州" for c in weather_calls)


def test_cache_hit_returns_cached_true(monkeypatch, db):
    _install_cfg(monkeypatch)
    _fake_get(monkeypatch)
    first = ws.fetch_weather("苏州", days=3, provider="uapis", db=db)
    assert first["cached"] is False

    def _should_not_call(*args, **kwargs):
        pytest.fail("缓存命中后不应再次请求上游")

    monkeypatch.setattr(ws.httpx, "get", _should_not_call)
    second = ws.fetch_weather("苏州", days=3, provider="uapis", db=db)
    assert second["cached"] is True
    assert second["current"] == first["current"]


def _insert_cache(db, cache_key, payload, *, expired):
    delta = timedelta(hours=-1 if expired else 1)
    db.add(WeatherCache(
        cache_key=cache_key, provider="uapis",
        payload_json=json.dumps(payload, ensure_ascii=False),
        fetched_at=ws._utc_naive(), expires_at=ws._utc_naive() + delta,
    ))
    db.commit()


def test_bad_current_not_written_to_cache(monkeypatch, db):
    """实况缺失（lives 为空）时不得写缓存：current 全为 None，且缓存表为空。"""
    _install_cfg(monkeypatch, provider="amap")
    _fake_get(monkeypatch, live=_AMAP_LIVE_EMPTY)
    data = ws.fetch_weather("苏州", provider="amap", db=db)
    assert data["current"]["weather"] is None
    assert data["current"]["temperature"] is None
    assert data["forecast"], "预报仍应返回"
    assert db.query(WeatherCache).count() == 0


def test_placeholder_cache_is_ignored_and_refetched(monkeypatch, db):
    """历史遗留的占位缓存不应命中：应重新拉取并改写为真实数据。"""
    _install_cfg(monkeypatch)
    _fake_get(monkeypatch)
    _insert_cache(db, "uapis:苏州:7", {
        "provider": "uapis", "city": "苏州",
        "current": {"weather": None, "temperature": None, "humidity": None,
                    "wind": None, "report_time": None, "alerts": []},
        "forecast": [], "advice_hints": [],
    }, expired=False)
    data = ws.fetch_weather("苏州", provider="uapis", db=db)
    assert data["cached"] is False
    assert data["current"]["temperature"] == 26.0


def test_bad_data_does_not_clear_good_cache(monkeypatch, db):
    """过期后若新数据实况缺失，不写缓存 -> 原有好缓存内容保持不变。"""
    _install_cfg(monkeypatch, provider="amap")
    good = {
        "provider": "amap", "city": "苏州",
        "current": {"weather": "晴", "temperature": 26.0, "humidity": 60,
                    "wind": "东南 3", "report_time": "t", "alerts": []},
        "forecast": [], "advice_hints": [],
    }
    _insert_cache(db, "amap:苏州:7", good, expired=True)
    _fake_get(monkeypatch, live=_AMAP_LIVE_EMPTY)
    ws.fetch_weather("苏州", provider="amap", db=db)
    row = db.query(WeatherCache).filter(WeatherCache.cache_key == "amap:苏州:7").first()
    assert row is not None
    stored = json.loads(row.payload_json)
    assert stored["current"]["temperature"] == 26.0, "好缓存不得被占位数据覆盖"


def test_provider_failure_raises_2006(monkeypatch, db):
    _install_cfg(monkeypatch)

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


def test_save_qweather_requires_host(monkeypatch, tmp_path):
    store = ConfigStore(path=tmp_path / "config.json")
    store.save({"installed": True})
    monkeypatch.setattr(cs, "_store", store)

    with pytest.raises(AppError) as exc:
        ws.save_weather_config({"provider": "qweather"})
    assert exc.value.code == ErrorCode.WEATHER_CONFIG_MISSING

    out = ws.save_weather_config({"provider": "qweather", "qweather_host": "https://" + QW_HOST + "/"})
    assert out["qweather_host"] == QW_HOST
    assert out["provider"] == "qweather"
