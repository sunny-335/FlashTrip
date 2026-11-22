"""天气服务：UApi Pro / 高德 / 和风三家归一化 + 缓存 + 出行提示词。

密钥经 encrypt() 存 config.json 的 weather 段 *_enc，仅在请求时 decrypt()；
统一 8s 超时；任一家失败抛 AppError(MAP_PROVIDER_ERROR, "天气服务暂不可用：...")。
缓存键 = provider+city+days，命中且未过期直接返回 cached=True。
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx

from app.core.config_store import get_config_store
from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger
from app.core.security import decrypt, encrypt
from app.models.weather import WeatherCache

log = get_logger(__name__)

PROVIDERS = ("uapis", "amap", "qweather")

_WEATHER_DEFAULTS: dict[str, Any] = {
    "provider": "uapis",
    "amap_key_enc": "",
    "qweather_key_enc": "",
    "uapi_key_enc": "",
    "cache_minutes": 60,
    "advice_days": 1,
}

# 前端提交明文键 -> 落盘密文字段
_SECRET_FIELDS = {
    "amap_key": "amap_key_enc",
    "qweather_key": "qweather_key_enc",
    "uapi_key": "uapi_key_enc",
}

_TIMEOUT = 8.0
_WEEK = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


# ---------------------------------------------------------------- 通用工具

def _utc_naive() -> datetime:
    """SQLite 取回的 DateTime 常为 naive，统一用 naive UTC 比较，避免时区类型冲突。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _as_naive(value: Any) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=None) if getattr(value, "tzinfo", None) else value


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _to_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value) or default


def _alerts(raw: Any) -> list[str]:
    """把上游 alerts[] 统一成字符串列表（兼容 dict / 字符串元素）。"""
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        if isinstance(item, dict):
            value = (item.get("title") or item.get("description") or item.get("desc")
                     or item.get("type") or item.get("text"))
        else:
            value = item
        text = _to_str(value)
        if text:
            out.append(text)
    return out


def _week_cn(value: Any) -> str:
    try:
        return _WEEK[date.fromisoformat(str(value)[:10]).weekday()]
    except (TypeError, ValueError):
        return ""


def _advice_hints(current: dict, forecast: list[dict]) -> list[str]:
    """基于归一化结果生成中文出行提示。"""
    hints: list[str] = []
    for alert in (current.get("alerts") or [])[:3]:
        hints.append(f"注意气象预警：{alert}")
    bad_words = ("雨", "雪", "雷", "雾", "霾")
    if any(
        any(word in (_to_str(f.get("weather_day")) + _to_str(f.get("weather_night"))) for word in bad_words)
        for f in forecast
    ):
        hints.append("近期有雨雪或低能见度天气，记得携带雨具并预留交通时间")
    if any(_to_float(f.get("pop")) >= 0.5 for f in forecast):
        hints.append("降水概率较高，建议准备防水装备")
    if any(_to_float(f.get("uv")) >= 6 for f in forecast):
        hints.append("紫外线较强，注意防晒与补水")
    temps = [_to_float(f.get("temp_max")) for f in forecast] + [_to_float(f.get("temp_min")) for f in forecast]
    if temps and max(temps) - min(temps) >= 10:
        hints.append("昼夜温差较大，建议分层穿衣")
    if not hints:
        hints.append("天气总体适宜出行，祝你旅途愉快")
    return hints


def _normalized(provider: str, city: str, current: dict,
                forecast: list[dict], days: int) -> dict:
    """统一三家输出结构，字段恒齐全。"""
    data: dict[str, Any] = {
        "provider": provider,
        "city": city,
        "current": {
            "weather": _to_str(current.get("weather"), "未知"),
            "temperature": _to_float(current.get("temperature")),
            "humidity": _to_int(current.get("humidity")),
            "wind": _to_str(current.get("wind"), "未知"),
            "report_time": _to_str(current.get("report_time")),
            "alerts": _alerts(current.get("alerts")),
        },
        "forecast": [
            {
                "date": _to_str(f.get("date")),
                "week": _to_str(f.get("week")),
                "weather_day": _to_str(f.get("weather_day")),
                "weather_night": _to_str(f.get("weather_night")),
                "temp_max": _to_float(f.get("temp_max")),
                "temp_min": _to_float(f.get("temp_min")),
                "wind": _to_str(f.get("wind")),
                "pop": _to_float(f.get("pop")),
                "uv": _to_float(f.get("uv")),
            }
            for f in (forecast or [])[:max(1, int(days))]
        ],
        "advice_hints": [],
        "cached": False,
    }
    data["advice_hints"] = _advice_hints(data["current"], data["forecast"])
    return data


# ---------------------------------------------------------------- 配置读写

def _raw_weather_config() -> dict:
    """读取含密文的内部配置（仅服务端使用）。"""
    section = get_config_store().load().get("weather")
    merged = dict(_WEATHER_DEFAULTS)
    if isinstance(section, dict):
        for key, value in section.items():
            if key in _WEATHER_DEFAULTS:
                merged[key] = value
    return merged


def get_weather_config() -> dict:
    """脱敏：所有 *_enc 只回 has_* 布尔。"""
    cfg = _raw_weather_config()
    return {
        "provider": cfg.get("provider"),
        "cache_minutes": cfg.get("cache_minutes"),
        "advice_days": cfg.get("advice_days"),
        "has_amap_key": bool(cfg.get("amap_key_enc")),
        "has_qweather_key": bool(cfg.get("qweather_key_enc")),
        "has_uapi_key": bool(cfg.get("uapi_key_enc")),
    }


def save_weather_config(cfg: dict) -> dict:
    """合并写入 config.json 的 weather 段；明文密钥加密，留空保留旧密文。"""
    store = get_config_store()
    full = store.load()
    section = dict(_WEATHER_DEFAULTS)
    if isinstance(full.get("weather"), dict):
        for key, value in full["weather"].items():
            if key in _WEATHER_DEFAULTS:
                section[key] = value
    for key, value in (cfg or {}).items():
        if key in _SECRET_FIELDS:
            if str(value or ""):
                section[_SECRET_FIELDS[key]] = encrypt(str(value))
        elif key == "provider":
            if value in PROVIDERS:
                section[key] = value
        elif key in _WEATHER_DEFAULTS and not key.endswith("_enc"):
            section[key] = value
    full["weather"] = section
    store.save(full)
    return get_weather_config()


# ---------------------------------------------------------------- 三家供应商

def _get_json(url: str, *, params: dict | None = None, headers: dict | None = None) -> dict:
    resp = httpx.get(url, params=params, headers=headers, timeout=_TIMEOUT)
    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, dict):
        raise RuntimeError("上游响应非对象")
    return payload


def _unwrap(payload: dict) -> dict:
    """兼容 UApi Pro 一类用 data 包裹响应的供应商。"""
    data = payload.get("data")
    if isinstance(data, dict) and any(
        key in data for key in ("weather", "forecast", "lives", "forecasts", "daily", "now")
    ):
        return data
    return payload


def _fetch_uapis(city: str, days: int, cfg: dict) -> dict:
    params = {
        "city": city,
        "forecast": "true",
        "extended": "true",
        "indices": "true",
        "lang": "zh",
    }
    headers: dict[str, str] = {}
    if cfg.get("uapi_key_enc"):
        key = decrypt(str(cfg["uapi_key_enc"]))
        if key:
            headers["Authorization"] = f"Bearer {key}"
    payload = _get_json("https://uapis.cn/api/v1/misc/weather", params=params, headers=headers)
    data = _unwrap(payload)
    if not (data.get("weather") or data.get("forecast")):
        raise RuntimeError("UApi Pro 未返回天气数据")
    current = {
        "weather": data.get("weather"),
        "temperature": data.get("temperature"),
        "humidity": data.get("humidity"),
        "wind": " ".join(
            part for part in (_to_str(data.get("wind_direction")), _to_str(data.get("wind_power"))) if part
        ).strip(),
        "report_time": data.get("report_time"),
        "alerts": data.get("alerts"),
    }
    forecast = []
    for item in data.get("forecast") or []:
        if not isinstance(item, dict):
            continue
        forecast.append({
            "date": item.get("date"),
            "week": item.get("week"),
            "weather_day": item.get("weather_day"),
            "weather_night": item.get("weather_night"),
            "temp_max": item.get("temp_max"),
            "temp_min": item.get("temp_min"),
            "wind": item.get("wind_dir_day") or item.get("wind_dir_night") or item.get("wind"),
            "pop": item.get("pop"),
            "uv": item.get("uv_index") or item.get("uv"),
        })
    return _normalized("uapis", city, current, forecast, days)


def _fetch_amap(city: str, days: int, cfg: dict) -> dict:
    key = decrypt(str(cfg.get("amap_key_enc") or "")) if cfg.get("amap_key_enc") else ""
    payload = _get_json(
        "https://restapi.amap.com/v3/weather/weatherInfo",
        params={"city": city, "key": key, "extensions": "all"},
    )
    lives = payload.get("lives") or []
    casts: list[Any] = []
    for group in payload.get("forecasts") or []:
        if isinstance(group, dict):
            casts.extend(group.get("casts") or [])
    if not lives and not casts:
        raise RuntimeError("高德未返回天气数据")
    live = lives[0] if isinstance(lives, list) and lives and isinstance(lives[0], dict) else {}
    current = {
        "weather": live.get("weather"),
        "temperature": live.get("temperature"),
        "humidity": live.get("humidity"),
        "wind": " ".join(
            part for part in (_to_str(live.get("winddirection")), _to_str(live.get("windpower"))) if part
        ).strip(),
        "report_time": live.get("reporttime"),
        "alerts": [],
    }
    forecast = []
    for item in casts:
        if not isinstance(item, dict):
            continue
        forecast.append({
            "date": item.get("date"),
            "week": item.get("week"),
            "weather_day": item.get("dayweather"),
            "weather_night": item.get("nightweather"),
            "temp_max": item.get("daytemp"),
            "temp_min": item.get("nighttemp"),
            "wind": item.get("daywind") or item.get("nightwind"),
            "pop": item.get("pop") or 0,
            "uv": 0,
        })
    return _normalized("amap", city, current, forecast, days)


def _fetch_qweather(city: str, days: int, cfg: dict) -> dict:
    key = decrypt(str(cfg.get("qweather_key_enc") or "")) if cfg.get("qweather_key_enc") else ""
    daily_payload = _get_json(
        "https://devapi.qweather.com/v7/weather/7d",
        params={"location": city, "key": key},
    )
    now_payload = _get_json(
        "https://devapi.qweather.com/v7/weather/now",
        params={"location": city, "key": key},
    )
    daily = daily_payload.get("daily") or []
    now = now_payload.get("now") or {}
    if not daily and not now:
        raise RuntimeError("和风未返回天气数据")
    current = {
        "weather": now.get("text"),
        "temperature": now.get("temp"),
        "humidity": now.get("humidity"),
        "wind": " ".join(
            part for part in (_to_str(now.get("windDir")), _to_str(now.get("windScale"))) if part
        ).strip(),
        "report_time": now.get("obsTime"),
        "alerts": [],
    }
    forecast = []
    for item in daily:
        if not isinstance(item, dict):
            continue
        forecast.append({
            "date": item.get("fxDate"),
            "week": _week_cn(item.get("fxDate")),
            "weather_day": item.get("textDay"),
            "weather_night": item.get("textNight"),
            "temp_max": item.get("tempMax"),
            "temp_min": item.get("tempMin"),
            "wind": item.get("windDirDay") or item.get("windDirNight"),
            "pop": item.get("pop"),
            "uv": item.get("uvIndex"),
        })
    return _normalized("qweather", city, current, forecast, days)


# ---------------------------------------------------------------- 缓存

def _get_session(db):
    if db is not None:
        return db, False
    try:
        from app.db.session import get_session
        return get_session()(), True
    except Exception as exc:
        log.warning("weather.cache_session_unavailable", error=type(exc).__name__)
        return None, False


def _read_cache(session, cache_key: str) -> dict | None:
    if session is None:
        return None
    try:
        row = session.query(WeatherCache).filter(WeatherCache.cache_key == cache_key).first()
        if row is None:
            return None
        expires = _as_naive(row.expires_at)
        if expires is not None and expires <= _utc_naive():
            return None
        payload = json.loads(row.payload_json or "{}")
        return payload if isinstance(payload, dict) else None
    except Exception as exc:
        log.warning("weather.cache_read_failed", error=type(exc).__name__)
        return None


def _write_cache(session, cache_key: str, provider: str, data: dict, cfg: dict) -> None:
    if session is None:
        return
    try:
        payload = {key: value for key, value in data.items() if key != "cached"}
        now = _utc_naive()
        expires = now + timedelta(minutes=max(1, _to_int(cfg.get("cache_minutes"), 60)))
        row = session.query(WeatherCache).filter(WeatherCache.cache_key == cache_key).first()
        if row is None:
            row = WeatherCache(cache_key=cache_key)
            session.add(row)
        row.provider = provider
        row.payload_json = json.dumps(payload, ensure_ascii=False, default=str)
        row.fetched_at = now
        row.expires_at = expires
        session.commit()
    except Exception as exc:
        log.warning("weather.cache_write_failed", error=type(exc).__name__)
        try:
            session.rollback()
        except Exception:
            log.warning("weather.cache_rollback_failed")


# ---------------------------------------------------------------- 对外主函数

def fetch_weather(city: str, *, days: int = 7, provider: str | None = None, db=None) -> dict:
    """统一归一化天气查询；命中有效缓存直接返回 cached=True。"""
    cfg = _raw_weather_config()
    prov = provider or cfg.get("provider") or "uapis"
    if prov not in PROVIDERS:
        raise AppError(ErrorCode.MAP_PROVIDER_ERROR, f"天气服务暂不可用：未知供应商 {prov}")
    city = str(city or "").strip()
    if not city:
        raise AppError(ErrorCode.VALIDATION, "城市名称不能为空")
    days = max(1, min(_to_int(days, 7), 15))
    cache_key = f"{prov}:{city}:{days}"

    session, owns = _get_session(db)
    try:
        cached = _read_cache(session, cache_key)
        if cached is not None:
            result = dict(cached)
            result["cached"] = True
            return result
        try:
            if prov == "uapis":
                data = _fetch_uapis(city, days, cfg)
            elif prov == "amap":
                data = _fetch_amap(city, days, cfg)
            else:
                data = _fetch_qweather(city, days, cfg)
        except AppError:
            raise
        except Exception as exc:
            raise AppError(
                ErrorCode.MAP_PROVIDER_ERROR,
                f"天气服务暂不可用：{type(exc).__name__}",
            ) from None
        data["cached"] = False
        _write_cache(session, cache_key, prov, data, cfg)
        return data
    finally:
        if owns and session is not None:
            try:
                session.close()
            except Exception:
                log.warning("weather.cache_close_failed")


def build_advice_prompt(trip: dict, weather: dict) -> str:
    """把行程日期/目的地/人数 + 天气拼成给 LLM 的中文提示词。"""
    trip = trip or {}
    weather = weather or {}
    current = weather.get("current") or {}
    lines = [
        "你是资深旅行管家，请根据以下行程与天气，输出简洁、可执行的中文出行建议"
        "（分点给出穿衣、交通、随身装备、防晒防雨与亲子/老人注意事项），不要编造未提供的信息。",
        f"行程标题：{trip.get('title') or '未命名行程'}",
        f"目的地：{trip.get('destination') or '未提供'}",
        f"出行日期：{trip.get('start_date') or '待定'} 至 {trip.get('end_date') or '待定'}",
        f"出行人数：{_to_int(trip.get('traveler_count'), 1)} 人，其中儿童 {_to_int(trip.get('children_count'), 0)} 人",
        "天气概况：",
        (f"  当前：{current.get('weather') or '未知'}，{current.get('temperature', '--')}℃，"
         f"湿度 {current.get('humidity', '--')}%，{current.get('wind') or '风力未知'}"),
    ]
    for item in (weather.get("forecast") or [])[:7]:
        lines.append(
            f"  {item.get('date') or ''} {item.get('week') or ''}："
            f"白天{item.get('weather_day') or '未知'}，夜间{item.get('weather_night') or '未知'}，"
            f"{item.get('temp_min', '--')}~{item.get('temp_max', '--')}℃，"
            f"降水概率 {item.get('pop', 0)}"
        )
    for hint in (weather.get("advice_hints") or []):
        lines.append(f"  提示：{hint}")
    return "\n".join(lines)


def check_upcoming_trips(db) -> list[dict]:
    """找出 start_date 落在未来 advice_days 天内、且未发过提醒的行程。"""
    try:
        from app.models.mail import MailLog
        from app.models.trip import Trip

        days = max(1, _to_int(_raw_weather_config().get("advice_days"), 1))
        today = date.today()
        deadline = today + timedelta(days=days)
        already = {
            row.trip_id
            for row in db.query(MailLog).filter(
                MailLog.template == "trip_weather_advice",
                MailLog.status == "sent",
                MailLog.trip_id.isnot(None),
            ).all()
        }
        trips = db.query(Trip).filter(
            Trip.start_date.isnot(None),
            Trip.start_date >= today,
            Trip.start_date <= deadline,
        ).all()
        out: list[dict] = []
        for trip in trips:
            if trip.id in already:
                continue
            out.append({
                "trip_id": trip.id,
                "title": trip.title,
                "destination": trip.destination,
                "start_date": trip.start_date.isoformat() if trip.start_date else "",
                "end_date": trip.end_date.isoformat() if trip.end_date else "",
                "traveler_count": _to_int(trip.traveler_count, 1),
                "children_count": _to_int(trip.children_count, 0),
            })
        return out
    except Exception as exc:
        log.warning("weather.upcoming_check_failed", error=type(exc).__name__)
        return []
