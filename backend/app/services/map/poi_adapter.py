"""POI 适配层：高德(GCJ-02) / 天地图(CGCS2000) 双源适配。

百度（BD-09）已随瓦片 Provider 一并删除：其瓦片坐标系与 Web Mercator 不
匹配、服务签名机制与本项目脱敏代理不兼容，实际不可用。

要点：
  - 所有结果「先 to_wgs84 再归一化」，输出坐标恒为 WGS84，coord_system 标记
    为 WGS84，并用 source_coord_system 保留来源坐标系便于追溯。
  - POI / 地理编码一律使用各供应商的「服务端 key」（高德 Web 服务 key、
    天地图 server_key；实测高德 JS key 调 Web 服务返回 INVALID_USER_KEY，
    绝不回退 JS key）。
  - geocode 独立实现：高德走专用 /v3/geocode/geo（地名 → 坐标，比关键词
    搜索更适合「地名自动填经纬度」）；天地图复用其地名搜索接口取首结果。
    返回结构同时携带 WGS84 与来源坐标系两组坐标。
  - 密钥只在后端解密后作为上游请求参数使用，绝不进入响应体、缓存与日志。
"""
from __future__ import annotations

import json
from collections import OrderedDict
from typing import Any

from app.core.config_store import get_config_store
from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger
from app.services.map.coord import to_wgs84
from app.services.map.credentials import resolve_service_key, service_key_ready
from app.services.map.http_client import TILE_USER_AGENT, upstream_client

log = get_logger(__name__)

_SOURCES: dict[str, dict[str, str]] = {
    "amap": {
        "coord": "GCJ02",
        "url": "https://restapi.amap.com/v3/place/text",
        "geocode_url": "https://restapi.amap.com/v3/geocode/geo",
    },
    "tianditu": {
        "coord": "CGCS2000",
        "url": "https://api.tianditu.gov.cn/v2/search",
        "geocode_url": "",  # 复用地名搜索实现地理编码
    },
}

_CACHE_MAX = 500
_POI_CACHE: "OrderedDict[str, dict]" = OrderedDict()


def _cfg(cfg: dict | None) -> dict:
    return cfg if cfg is not None else get_config_store().load()


def pick_provider(cfg: dict | None, provider: str | None) -> str:
    """确定查询供应商：优先显式指定，否则挑服务端 key 已就绪的供应商。"""
    cfg = _cfg(cfg)
    if provider:
        if provider in _SOURCES:
            return provider
        # 百度已删除：显式传入时给出明确错误而不是静默换源
        raise AppError(ErrorCode.MAP_PROVIDER_ERROR, f"不支持的地图服务供应商：{provider}")
    for candidate in ("amap", "tianditu"):
        if service_key_ready(cfg, candidate):
            return candidate
    raise AppError(
        ErrorCode.MAP_SERVICE_KEY_MISSING,
        "尚未配置可用的地图服务密钥（高德 Web 服务 key 或天地图 server key），请先在设置中填写",
    )


def _request(url: str, params: dict[str, Any], provider: str) -> dict:
    """上游 HTTP 调用；异常信息只记录类型，绝不把带 key 的 URL 写进日志或错误。"""
    try:
        with upstream_client() as client:
            resp = client.get(url, params=params, headers={"User-Agent": TILE_USER_AGENT})
        if resp.status_code != 200:
            log.warning("map.poi_http_status", provider=provider, status=resp.status_code)
            raise AppError(ErrorCode.MAP_PROVIDER_ERROR, "地图服务暂时不可用，请稍后重试")
        return resp.json()
    except AppError:
        raise
    except Exception as exc:  # noqa: BLE001
        log.warning("map.poi_request_failed", provider=provider, error_type=type(exc).__name__)
        raise AppError(ErrorCode.MAP_PROVIDER_ERROR, "地图服务连接失败，请稍后重试") from None


def _service_key(cfg: dict, provider: str) -> str:
    """取服务端 key；未配置时给出可行动的明确错误（而不是含糊的 502）。"""
    key = resolve_service_key(cfg, provider)
    if not key:
        raise AppError(
            ErrorCode.MAP_SERVICE_KEY_MISSING,
            f"尚未配置{provider_label(provider)}服务密钥，请先在设置中填写",
        )
    return key


def provider_label(provider: str) -> str:
    return {"amap": "高德", "tianditu": "天地图"}.get(provider, provider)


def _split_lnglat(raw: Any) -> tuple[float, float] | None:
    if isinstance(raw, dict):
        raw_lng, raw_lat = raw.get("lng"), raw.get("lat")
    elif isinstance(raw, str) and "," in raw:
        parts = raw.split(",", 1)
        raw_lng, raw_lat = parts[0], parts[1]
    else:
        return None
    try:
        lng, lat = float(raw_lng), float(raw_lat)
    except (TypeError, ValueError):
        return None
    if lng == 0.0 and lat == 0.0:
        return None
    return lng, lat


def _normalize(item: dict, provider: str, raw_point: Any) -> dict | None:
    """单条 POI：先转 WGS84 再归一化。"""
    src = _SOURCES[provider]["coord"]
    point = _split_lnglat(raw_point)
    if point is None:
        return None
    w_lng, w_lat = to_wgs84(point[0], point[1], src)
    raw_id = str(item.get("id") or item.get("uid") or f"{w_lng:.6f},{w_lat:.6f}")
    name = str(item.get("name") or "")
    if not name:
        return None
    return {
        "id": f"{provider}:{raw_id}",
        "name": name,
        "address": str(item.get("address") or ""),
        "lng": round(w_lng, 7),
        "lat": round(w_lat, 7),
        "coord_system": "WGS84",
        "source_coord_system": src,
        "source_lng": round(point[0], 7),
        "source_lat": round(point[1], 7),
        "category": str(item.get("type") or item.get("typecode") or item.get("poiType") or ""),
        "provider": provider,
        "raw": {
            "id": raw_id,
            "name": name,
            "address": str(item.get("address") or ""),
            "lng": point[0],
            "lat": point[1],
            "coord_system": src,
            "category": str(item.get("type") or item.get("typecode") or item.get("poiType") or ""),
        },
    }


def _cache_put(poi: dict) -> None:
    _POI_CACHE[poi["id"]] = poi
    _POI_CACHE.move_to_end(poi["id"])
    while len(_POI_CACHE) > _CACHE_MAX:
        _POI_CACHE.popitem(last=False)


def search_poi(q: str, provider: str | None = None, city: str = "", cfg: dict | None = None) -> list[dict]:
    """关键词 / 地址搜索（服务端 key），返回按 WGS84 归一化后的 POI 列表。"""
    q = (q or "").strip()
    if not q:
        raise AppError(ErrorCode.VALIDATION, "搜索关键词不能为空")
    cfg = _cfg(cfg)
    provider = pick_provider(cfg, provider)
    key = _service_key(cfg, provider)

    if provider == "amap":
        params: dict[str, Any] = {
            "key": key, "keywords": q, "city": city or "", "output": "json",
            "offset": 20, "page": 1, "extensions": "base",
        }
    else:
        post = {
            "keyWord": q, "level": 12, "mapBound": "-180,-90,180,90",
            "queryType": 1, "count": 20, "start": 0,
        }
        params = {"postStr": json.dumps(post, ensure_ascii=False), "type": "query", "tk": key}

    data = _request(_SOURCES[provider]["url"], params, provider)

    if provider == "amap":
        if str(data.get("status")) != "1":
            raise AppError(ErrorCode.MAP_PROVIDER_ERROR, "高德地点搜索未返回结果")
        items = data.get("pois") or []
        raw_points = [(it, it.get("location")) for it in items if isinstance(it, dict)]
    else:
        if str(data.get("status")) not in ("0", "None", "100"):
            raise AppError(ErrorCode.MAP_PROVIDER_ERROR, "天地图地点搜索未返回结果")
        result = data.get("result") or data.get("pois") or []
        if isinstance(result, dict):
            result = result.get("poiList") or []
        items = result if isinstance(result, list) else []
        raw_points = [(it, it.get("lonlat")) for it in items if isinstance(it, dict)]

    pois: list[dict] = []
    for item, raw_point in raw_points:
        poi = _normalize(item, provider, raw_point)
        if poi is not None:
            _cache_put(poi)
            pois.append(poi)
    return pois


def get_poi(poi_id: str, provider: str | None = None, cfg: dict | None = None) -> dict:
    """按归一化 id 取详情（进程内短缓存；失效则要求前端重新搜索）。"""
    poi = _POI_CACHE.get(poi_id)
    if poi is None:
        raise AppError(ErrorCode.MAP_PROVIDER_ERROR, "地点信息已失效，请重新搜索")
    _POI_CACHE.move_to_end(poi_id)
    return poi


def _geocode_result(provider: str, name: str, address: str,
                    src_lng: float, src_lat: float) -> dict:
    """统一地理编码返回结构：WGS84 与来源坐标系两组坐标都给齐。"""
    src = _SOURCES[provider]["coord"]
    w_lng, w_lat = to_wgs84(src_lng, src_lat, src)
    return {
        "name": name,
        "address": address or name,
        "provider": provider,
        # 结构化坐标（推荐前端使用）
        "location": {"lng": round(w_lng, 7), "lat": round(w_lat, 7), "coord_system": "WGS84"},
        "source_location": {
            "lng": round(src_lng, 7), "lat": round(src_lat, 7), "coord_system": src,
        },
        # 扁平字段（沿用 POI 契约，前端可直接自动填经纬度）
        "lng": round(w_lng, 7),
        "lat": round(w_lat, 7),
        "coord_system": "WGS84",
        "source_coord_system": src,
        "source_lng": round(src_lng, 7),
        "source_lat": round(src_lat, 7),
    }


def _geocode_amap(address: str, city: str, key: str) -> dict:
    """高德专用地理编码：/v3/geocode/geo（地名 → 坐标，含行政区划信息）。"""
    params: dict[str, Any] = {
        "key": key, "address": address, "city": city or "", "output": "json",
    }
    data = _request(_SOURCES["amap"]["geocode_url"], params, "amap")
    if str(data.get("status")) != "1":
        info = str(data.get("info") or "")
        raise AppError(ErrorCode.MAP_PROVIDER_ERROR, f"高德地理编码失败：{info or '未返回结果'}")
    items = data.get("geocodes") or []
    for item in items:
        if not isinstance(item, dict):
            continue
        point = _split_lnglat(item.get("location"))
        if point is None:
            continue
        name = str(item.get("short_address") or item.get("formatted_address") or address)
        return _geocode_result("amap", name, str(item.get("formatted_address") or ""), *point)
    raise AppError(ErrorCode.MAP_PROVIDER_ERROR, "未找到该地址对应的地点")


def geocode(address: str, provider: str | None = None, city: str = "", cfg: dict | None = None) -> dict:
    """地理编码（地名 → 坐标）：高德走专用 API，天地图复用地名搜索取首结果。"""
    address = (address or "").strip()
    if not address:
        raise AppError(ErrorCode.VALIDATION, "地址不能为空")
    cfg = _cfg(cfg)
    provider = pick_provider(cfg, provider)
    key = _service_key(cfg, provider)
    if provider == "amap":
        return _geocode_amap(address, city, key)
    # 天地图：地名搜索本身支持地址解析，取首个结果包装为地理编码结构
    pois = search_poi(address, provider=provider, city=city, cfg=cfg)
    if not pois:
        raise AppError(ErrorCode.MAP_PROVIDER_ERROR, "未找到该地址对应的地点")
    first = pois[0]
    return _geocode_result(
        provider, first["name"], first["address"],
        first["source_lng"], first["source_lat"],
    )


def provider_supported_ids() -> list[str]:
    """供 /map/providers 之外的地方复用：有 POI 能力的供应商 id 列表。"""
    return list(_SOURCES)
