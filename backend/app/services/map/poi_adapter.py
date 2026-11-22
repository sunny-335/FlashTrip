"""POI 适配层：高德(GCJ-02) / 百度(BD-09) / 天地图(CGCS2000)。

所有结果「先 to_wgs84 再归一化」，输出坐标恒为 WGS84，coord_system 标记为
WGS84，并用 source_coord_system 保留来源坐标系便于追溯。密钥只在后端 decrypt
后作为上游请求参数使用，绝不进入响应体、缓存内容与日志。
"""
from __future__ import annotations

import json
from collections import OrderedDict
from typing import Any

import httpx

from app.core.config_store import get_config_store
from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger
from app.services.map.coord import to_wgs84
from app.services.map.provider_registry import (
    PROVIDER_DEFS,
    _provider_entries,
    get_provider_key,
)

log = get_logger(__name__)

_SOURCES: dict[str, dict[str, str]] = {
    "amap": {
        "coord": "GCJ02",
        "url": "https://restapi.amap.com/v3/place/text",
    },
    "baidu": {
        "coord": "BD09",
        "url": "https://api.map.baidu.com/place/v2/search",
    },
    "tianditu": {
        "coord": "CGCS2000",
        "url": "https://api.tianditu.gov.cn/v2/search",
    },
}

_CACHE_MAX = 500
_POI_CACHE: OrderedDict[str, dict] = OrderedDict()


def _cfg(cfg: dict | None) -> dict:
    return cfg if cfg is not None else get_config_store().load()


def pick_provider(cfg: dict | None, provider: str | None) -> str:
    """确定 POI 查询供应商：优先显式指定，否则挑已配置密钥的国内供应商。"""
    cfg = _cfg(cfg)
    if provider:
        if provider in _SOURCES:
            return provider
        raise AppError(ErrorCode.MAP_PROVIDER_ERROR, f"不支持的 POI 供应商：{provider}")
    entries = _provider_entries(cfg)
    for candidate in ("amap", "tianditu", "baidu"):
        entry = entries.get(candidate, {})
        if entry.get("key_enc") or entry.get("api_key_enc") or entry.get("token_enc"):
            return candidate
    raise AppError(ErrorCode.MAP_PROVIDER_ERROR, "尚未配置可用的 POI 搜索密钥，请先在设置中填写")


def _request(url: str, params: dict[str, Any], provider: str) -> dict:
    """上游 HTTP 调用；异常信息只记录类型，绝不把带 key 的 URL 写进日志或错误。"""
    try:
        with httpx.Client(timeout=10.0, follow_redirects=True) as client:
            resp = client.get(url, params=params)
        if resp.status_code != 200:
            log.warning("map.poi_http_status", provider=provider, status=resp.status_code)
            raise AppError(ErrorCode.MAP_PROVIDER_ERROR, "地图服务暂时不可用，请稍后重试")
        return resp.json()
    except AppError:
        raise
    except Exception as exc:  # noqa: BLE001
        log.warning("map.poi_request_failed", provider=provider, error_type=type(exc).__name__)
        raise AppError(ErrorCode.MAP_PROVIDER_ERROR, "地图服务连接失败，请稍后重试") from None


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
    """关键词 / 地址搜索，返回按 WGS84 归一化后的 POI 列表。"""
    q = (q or "").strip()
    if not q:
        raise AppError(ErrorCode.VALIDATION, "搜索关键词不能为空")
    cfg = _cfg(cfg)
    provider = pick_provider(cfg, provider)
    key = get_provider_key(cfg, provider)

    if provider == "amap":
        params: dict[str, Any] = {
            "key": key, "keywords": q, "city": city or "", "output": "json",
            "offset": 20, "page": 1, "extensions": "base",
        }
    elif provider == "baidu":
        params = {
            "ak": key, "query": q, "region": city or "全国", "output": "json",
            "scope": 1, "page_size": 20, "page_num": 0,
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
    elif provider == "baidu":
        if str(data.get("status")) != "0":
            raise AppError(ErrorCode.MAP_PROVIDER_ERROR, "百度地点搜索未返回结果")
        items = data.get("results") or []
        raw_points = [(it, it.get("location")) for it in items if isinstance(it, dict)]
    else:
        if str(data.get("status")) not in ("0", "None"):
            raise AppError(ErrorCode.MAP_PROVIDER_ERROR, "天地图地点搜索未返回结果")
        result = data.get("result") or []
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


def geocode(address: str, provider: str | None = None, city: str = "", cfg: dict | None = None) -> dict:
    """地理编码：复用地点搜索并取首个结果。"""
    pois = search_poi(address, provider=provider, city=city, cfg=cfg)
    if not pois:
        raise AppError(ErrorCode.MAP_PROVIDER_ERROR, "未找到该地址对应的地点")
    return pois[0]


def provider_supported_ids() -> list[str]:
    """供 /map/providers 之外的地方复用：有 POI 能力的供应商 id 列表。"""
    return [d["id"] for d in PROVIDER_DEFS if d["id"] in _SOURCES]
