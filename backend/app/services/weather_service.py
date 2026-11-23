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
    # 和风新版要求「账号专属 API Host」（形如 abc123.re.qweatherapi.com），
    # 不再使用已废弃的共享 devapi 域名；JWT 为 API KEY 的可选替代凭据。
    "qweather_host": "",
    "qweather_jwt_enc": "",
    "uapi_key_enc": "",
    "cache_minutes": 60,
    "advice_days": 1,
    # 旅行中每日早晨天气邮件：是否开启 + 发送时刻（24 小时制 HH:MM）。
    # 默认关闭：邮件功能属主动开启项，避免用户配置完邮箱后意外收到每日邮件。
    "daily_reminder_enabled": False,
    "daily_reminder_time": "07:30",
}

# 前端提交明文键 -> 落盘密文字段
_SECRET_FIELDS = {
    "amap_key": "amap_key_enc",
    "qweather_key": "qweather_key_enc",
    "qweather_jwt": "qweather_jwt_enc",
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


# 归一化「缺失即缺失」：缺数据一律返回 None，绝不再用 0 / "未知" 之类的占位值
# 污染对外结果与缓存（占位值会让用户误以为拿到了真实天气）。

def _opt_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _opt_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_host(value: Any) -> str:
    """把用户填写的 Host 归一为纯净域名：去协议头与首尾斜杠/空白。"""
    host = str(value or "").strip()
    for prefix in ("https://", "http://"):
        if host.lower().startswith(prefix):
            host = host[len(prefix):]
    return host.split("/", 1)[0].strip()


def _normalize_hhmm(value: Any) -> str:
    """校验并归一 HH:MM；非法输入回退为 07:30。"""
    text = str(value or "").strip()
    try:
        hour_s, minute_s = text.split(":", 1)
        hour, minute = int(hour_s), int(minute_s)
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}"
    except (ValueError, TypeError):
        pass
    return "07:30"


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
    has_any = bool(_opt_str(current.get("weather"))) or current.get("temperature") is not None or bool(forecast)
    if not has_any:
        # 实况与预报全部缺失时不能给出「适宜出行」之类的误导性结论
        return ["暂无天气数据，请稍后重试或检查天气服务配置"]
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
    """统一三家输出结构，字段恒齐全；缺失字段一律为 None（不再回填占位值）。"""
    data: dict[str, Any] = {
        "provider": provider,
        "city": city,
        "current": {
            "weather": _opt_str(current.get("weather")),
            "temperature": _opt_float(current.get("temperature")),
            "humidity": _opt_int(current.get("humidity")),
            "wind": _opt_str(current.get("wind")),
            "report_time": _opt_str(current.get("report_time")),
            "alerts": _alerts(current.get("alerts")),
        },
        "forecast": [
            {
                "date": _to_str(f.get("date")),
                "week": _to_str(f.get("week")),
                "weather_day": _opt_str(f.get("weather_day")),
                "weather_night": _opt_str(f.get("weather_night")),
                "temp_max": _opt_float(f.get("temp_max")),
                "temp_min": _opt_float(f.get("temp_min")),
                "wind": _opt_str(f.get("wind")),
                "pop": _opt_float(f.get("pop")),
                "uv": _opt_float(f.get("uv")),
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
    """脱敏：所有 *_enc 只回 has_* 布尔；Host 为可公开展示的域名。"""
    cfg = _raw_weather_config()
    return {
        "provider": cfg.get("provider"),
        "cache_minutes": cfg.get("cache_minutes"),
        "advice_days": cfg.get("advice_days"),
        "qweather_host": cfg.get("qweather_host") or "",
        "has_amap_key": bool(cfg.get("amap_key_enc")),
        "has_qweather_key": bool(cfg.get("qweather_key_enc")),
        "has_qweather_jwt": bool(cfg.get("qweather_jwt_enc")),
        "has_uapi_key": bool(cfg.get("uapi_key_enc")),
        "daily_reminder_enabled": bool(cfg.get("daily_reminder_enabled")),
        "daily_reminder_time": _normalize_hhmm(cfg.get("daily_reminder_time")),
    }


def get_daily_reminder_config() -> dict:
    """旅行中每日天气提醒的调度配置（供调度器读取，已归一化）。"""
    cfg = _raw_weather_config()
    return {
        "enabled": bool(cfg.get("daily_reminder_enabled")),
        "time": _normalize_hhmm(cfg.get("daily_reminder_time")),
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
        elif key == "qweather_host":
            section["qweather_host"] = _normalize_host(value)
        elif key == "daily_reminder_time":
            section["daily_reminder_time"] = _normalize_hhmm(value)
        elif key == "daily_reminder_enabled":
            section["daily_reminder_enabled"] = bool(value)
        elif key in _WEATHER_DEFAULTS and not key.endswith("_enc"):
            section[key] = value
    # 和风必填校验：选择 qweather 供应商时必须有账号专属 Host，否则请求必然失败
    if section.get("provider") == "qweather" and not section.get("qweather_host"):
        raise AppError(
            ErrorCode.WEATHER_CONFIG_MISSING,
            "选择和风天气时必须填写账号专属 API Host（形如 abc123.re.qweatherapi.com），请在设置-天气中补充",
        )
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


_AMAP_WEATHER_API = "https://restapi.amap.com/v3/weather/weatherInfo"
_AMAP_DISTRICT_API = "https://restapi.amap.com/v3/config/district"


def _resolve_amap_adcode(city: str, key: str) -> str:
    """通过高德行政区划接口把城市名转成 adcode；失败时降级为城市名并记录日志。

    高德天气接口的 city 参数必须是 adcode（行政区划编码）或「城市名+adcode」，
    直接传中文城市名在部分城市会返回空 lives / forecasts。已是纯数字 adcode 时直接复用。
    """
    city = str(city or "").strip()
    if not city:
        return city
    if city.isdigit() and len(city) >= 6:
        return city
    if not key:
        log.warning("weather.amap_adcode_no_key", city=city)
        return city
    try:
        payload = _get_json(
            _AMAP_DISTRICT_API,
            params={"keywords": city, "key": key, "subdistrict": "0", "extensions": "base"},
        )
        districts = payload.get("districts") or []
        if isinstance(districts, list) and districts and isinstance(districts[0], dict):
            adcode = str(districts[0].get("adcode") or "").strip()
            if adcode:
                return adcode
        log.warning("weather.amap_adcode_missing", city=city)
    except Exception as exc:  # noqa: BLE001  异常可能回显含 key 的 URL，只记录类型
        log.warning("weather.amap_adcode_failed", city=city, error=type(exc).__name__)
    # 降级：用城市名请求（高德在多数地级市仍可识别），并已记录日志便于排查
    return city


def _amap_check(payload: dict, action: str) -> None:
    """上游 status != 1 时把 info/infocode 作为原因透出（不含 key）。"""
    status = str(payload.get("status") or "")
    if status and status != "1":
        info = str(payload.get("info") or "").strip()
        info_code = str(payload.get("infocode") or "").strip()
        reason = " / ".join(part for part in (info, info_code) if part) or "未知错误"
        raise AppError(
            ErrorCode.MAP_PROVIDER_ERROR,
            f"高德天气{action}失败：{reason}",
        )


def _fetch_amap(city: str, days: int, cfg: dict) -> dict:
    key = decrypt(str(cfg.get("amap_key_enc") or "")) if cfg.get("amap_key_enc") else ""
    if not key:
        raise AppError(
            ErrorCode.WEATHER_CONFIG_MISSING,
            "尚未配置高德天气 API Key，请前往设置-天气填写",
        )
    adcode = _resolve_amap_adcode(city, key)
    # 高德：extensions=base 只返实况 lives，extensions=all 只返预报 forecasts，
    # 二者必须分离请求；此前只用 all 会导致 current 永远为空。
    try:
        base = _get_json(
            _AMAP_WEATHER_API,
            params={"city": adcode, "key": key, "extensions": "base"},
        )
        forecast_payload = _get_json(
            _AMAP_WEATHER_API,
            params={"city": adcode, "key": key, "extensions": "all"},
        )
    except AppError:
        raise
    except httpx.HTTPStatusError as exc:
        raise AppError(
            ErrorCode.MAP_PROVIDER_ERROR,
            f"高德天气服务返回 HTTP {exc.response.status_code}",
        ) from None
    except Exception as exc:  # noqa: BLE001  异常可能含 key，只记录类型
        raise AppError(
            ErrorCode.MAP_PROVIDER_ERROR,
            f"高德天气服务请求失败：{type(exc).__name__}",
        ) from None

    _amap_check(base, "实况查询")
    _amap_check(forecast_payload, "预报查询")
    lives = base.get("lives") or []
    casts: list[Any] = []
    for group in forecast_payload.get("forecasts") or []:
        if isinstance(group, dict):
            casts.extend(group.get("casts") or [])
    if not lives and not casts:
        raise AppError(ErrorCode.MAP_PROVIDER_ERROR, "高德天气未返回任何数据，请检查城市与 adcode")
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


_QWEATHER_GEO_API = "https://geoapi.qweather.com/v2/city/lookup"

# 和风常见返回码 -> 可读中文，便于把上游原因透出给用户/日志
_QWEATHER_CODE_HINT = {
    "204": "请求成功但该地区无数据",
    "400": "请求参数有误",
    "401": "认证失败，请检查 API KEY / JWT",
    "402": "超出访问次数或余额不足",
    "403": "无访问权限，请检查账号与 Host 是否匹配",
    "404": "查询的地区或数据不存在",
    "429": "请求过于频繁，已被限流",
    "500": "和风服务端错误",
}


def _qweather_credentials(cfg: dict) -> tuple[str, str]:
    """解出 (api_key, jwt) 明文，仅在本函数返回值中短暂存在。"""
    key = decrypt(str(cfg.get("qweather_key_enc") or "")) if cfg.get("qweather_key_enc") else ""
    jwt = decrypt(str(cfg.get("qweather_jwt_enc") or "")) if cfg.get("qweather_jwt_enc") else ""
    return key, jwt


def _qweather_headers(key: str, jwt: str) -> dict[str, str]:
    """实况/预报走新版 Host，凭据放在请求头：API KEY 用 X-QW-Api-Key，JWT 用 Bearer。"""
    if key:
        return {"X-QW-Api-Key": key}
    if jwt:
        return {"Authorization": f"Bearer {jwt}"}
    return {}


def _qweather_code_error(payload: dict, action: str) -> None:
    """上游返回非 200 业务码时抛出带原因的中文错误。"""
    code = str(payload.get("code") or "")
    if code and code != "200":
        hint = _QWEATHER_CODE_HINT.get(code, "未知错误")
        raise AppError(
            ErrorCode.MAP_PROVIDER_ERROR,
            f"和风天气{action}失败：错误码 {code}（{hint}）",
        )


def _qweather_location_id(city: str, key: str, jwt: str) -> str | None:
    """GeoAPI 城市检索：把城市名换成 LocationID；无结果返回 None。"""
    params: dict[str, Any] = {"location": city, "number": "1"}
    headers: dict[str, str] = {}
    if key:
        params["key"] = key
    elif jwt:
        headers["Authorization"] = f"Bearer {jwt}"
    try:
        payload = _get_json(_QWEATHER_GEO_API, params=params, headers=headers or None)
    except AppError:
        raise
    except httpx.HTTPStatusError as exc:
        raise AppError(
            ErrorCode.MAP_PROVIDER_ERROR,
            f"和风天气城市检索返回 HTTP {exc.response.status_code}",
        ) from None
    except Exception as exc:  # noqa: BLE001  异常可能回显含 key 的 URL，只记录类型
        raise AppError(
            ErrorCode.MAP_PROVIDER_ERROR,
            f"和风天气城市检索失败：{type(exc).__name__}",
        ) from None
    _qweather_code_error(payload, "城市检索")
    locations = payload.get("location") or []
    if not isinstance(locations, list) or not locations:
        return None
    first = locations[0]
    if not isinstance(first, dict):
        return None
    return str(first.get("id") or "").strip() or None


def _fetch_qweather(city: str, days: int, cfg: dict) -> dict:
    key, jwt = _qweather_credentials(cfg)
    host = _normalize_host(cfg.get("qweather_host"))
    if not host:
        raise AppError(
            ErrorCode.WEATHER_CONFIG_MISSING,
            "尚未配置和风天气 API Host，请前往设置-天气填写账号专属 Host"
            "（形如 abc123.re.qweatherapi.com，可在和风控制台查看）",
        )
    headers = _qweather_headers(key, jwt)
    if not headers:
        raise AppError(
            ErrorCode.WEATHER_CONFIG_MISSING,
            "尚未配置和风天气 API KEY 或 JWT，请前往设置-天气填写其中一项",
        )
    location = _qweather_location_id(city, key, jwt)
    if not location:
        raise AppError(
            ErrorCode.MAP_PROVIDER_ERROR,
            f"和风天气未能识别城市「{city}」，请检查城市名称是否正确",
        )
    base = f"https://{host}/v7/weather"
    try:
        now_payload = _get_json(f"{base}/now", params={"location": location}, headers=headers)
        daily_payload = _get_json(f"{base}/7d", params={"location": location}, headers=headers)
    except AppError:
        raise
    except httpx.HTTPStatusError as exc:
        raise AppError(
            ErrorCode.MAP_PROVIDER_ERROR,
            f"和风天气服务返回 HTTP {exc.response.status_code}，请检查 Host 是否正确",
        ) from None
    except Exception as exc:  # noqa: BLE001  异常可能含凭据，只记录类型
        raise AppError(
            ErrorCode.MAP_PROVIDER_ERROR,
            f"和风天气服务请求失败：{type(exc).__name__}",
        ) from None
    _qweather_code_error(now_payload, "实况天气查询")
    _qweather_code_error(daily_payload, "逐日预报查询")
    daily = daily_payload.get("daily") or []
    now = now_payload.get("now") or {}
    if not daily and not now:
        raise AppError(ErrorCode.MAP_PROVIDER_ERROR, "和风天气未返回任何数据")
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

def _payload_has_quality(data: dict) -> bool:
    """质量门禁：实况至少要有真实天气文字或数值温度，才允许写缓存 / 命中缓存。

    仅含预报、或实况为 None/占位的数据不算合格——避免把「空实况」写入缓存，
    也避免把历史遗留的占位缓存继续返回给用户。
    """
    current = (data or {}).get("current") or {}
    weather = current.get("weather")
    if isinstance(weather, str) and weather.strip() and weather != "未知":
        return True
    return current.get("temperature") is not None


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
        # 质量门禁：只返回合格缓存；占位/空实况缓存视为未命中，触发重新拉取
        if cached is not None and _payload_has_quality(cached):
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
        # 质量门禁：实况缺失/占位时不写缓存，也不清空已有好缓存（不写即保留）
        if _payload_has_quality(data):
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
        (f"  当前：{current.get('weather') or '未知'}，"
         f"{current.get('temperature') if current.get('temperature') is not None else '--'}℃，"
         f"湿度 {current.get('humidity') if current.get('humidity') is not None else '--'}%，"
         f"{current.get('wind') or '风力未知'}"),
    ]
    for item in (weather.get("forecast") or [])[:7]:
        tmin = item.get("temp_min")
        tmax = item.get("temp_max")
        lines.append(
            f"  {item.get('date') or ''} {item.get('week') or ''}："
            f"白天{item.get('weather_day') or '未知'}，夜间{item.get('weather_night') or '未知'}，"
            f"{tmin if tmin is not None else '--'}~{tmax if tmax is not None else '--'}℃，"
            f"降水概率 {item.get('pop') if item.get('pop') is not None else 0}"
        )
    for hint in (weather.get("advice_hints") or []):
        lines.append(f"  提示：{hint}")
    return "\n".join(lines)


def _trip_brief(trip) -> dict:
    """行程 ORM -> 供邮件/提示词使用的精简字典。"""
    return {
        "trip_id": trip.id,
        "title": trip.title,
        "destination": trip.destination,
        "start_date": trip.start_date.isoformat() if trip.start_date else "",
        "end_date": trip.end_date.isoformat() if trip.end_date else "",
        "traveler_count": _to_int(trip.traveler_count, 1),
        "children_count": _to_int(trip.children_count, 0),
    }


def check_upcoming_trips(db) -> list[dict]:
    """找出 start_date 落在「today 之后、未来 advice_days 天内」且未发过提醒的行程。

    边界用严格大于 today：出发当天交由「每日在途提醒」负责，避免同一天发两封。
    """
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
            Trip.start_date > today,
            Trip.start_date <= deadline,
        ).all()
        return [_trip_brief(trip) for trip in trips if trip.id not in already]
    except Exception as exc:
        log.warning("weather.upcoming_check_failed", error=type(exc).__name__)
        return []


def check_active_trips(db, today: date | None = None) -> list[dict]:
    """找出「当前日期落在行程日期范围内」的在途行程（用于每日早晨天气邮件）。"""
    try:
        from app.models.trip import Trip

        today = today or date.today()
        trips = db.query(Trip).filter(
            Trip.start_date.isnot(None),
            Trip.start_date <= today,
            Trip.end_date.isnot(None),
            Trip.end_date >= today,
        ).all()
        out: list[dict] = []
        for trip in trips:
            # 已结束/归档的行程即便日期仍覆盖今天也不再打扰
            if str(getattr(trip, "status", "") or "") in ("completed", "archived"):
                continue
            out.append(_trip_brief(trip))
        return out
    except Exception as exc:
        log.warning("weather.active_check_failed", error=type(exc).__name__)
        return []
