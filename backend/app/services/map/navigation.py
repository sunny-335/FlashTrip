"""导航深链工具：高德 / 百度 / 腾讯地图的 URL。

各厂商 URI 的坐标系口径不同，统一先把入参坐标归一化到 WGS84，再转换：
  - 高德 / 腾讯使用 GCJ-02；百度使用 BD-09。
  - 名称一律 URL 编码，避免中文与特殊字符破坏查询参数。
注意：这里的百度只是「导航 App 深链」，与已删除的百度瓦片 Provider 无关。
"""
from __future__ import annotations

from typing import Any
from urllib.parse import quote

from pydantic import BaseModel, Field

from app.core.errors import AppError, ErrorCode
from app.services.map.coord import from_wgs84, to_wgs84


class NavigationTargetIn(BaseModel):
    name: str = ""
    lng: float
    lat: float
    # 入参坐标系（前端 POI 为 WGS84；也支持 GCJ02 / BD09 / CGCS2000）
    coord_system: str = "WGS84"


_APP_LABELS = {
    "amap": "高德地图",
    "baidu": "百度地图",
    "tencent": "腾讯地图",
}


def _coords(lng: float, lat: float, coord_system: str) -> dict[str, tuple[float, float]]:
    """一次算出 WGS84 / GCJ-02 / BD-09 三组坐标，避免重复转换。"""
    try:
        w_lng, w_lat = to_wgs84(lng, lat, coord_system)
        g_lng, g_lat = from_wgs84(w_lng, w_lat, "GCJ02")
        b_lng, b_lat = from_wgs84(w_lng, w_lat, "BD09")
    except ValueError as exc:
        raise AppError(ErrorCode.VALIDATION, f"坐标参数错误：{exc}") from None
    return {
        "WGS84": (round(w_lng, 7), round(w_lat, 7)),
        "GCJ02": (round(g_lng, 7), round(g_lat, 7)),
        "BD09": (round(b_lng, 7), round(b_lat, 7)),
    }


def build_navigation_links(payload: NavigationTargetIn) -> dict[str, Any]:
    """返回中国境内合规导航软件的可直接跳转 URL（坐标系已转换并标注）。"""
    name = (payload.name or "目的地").strip() or "目的地"
    qname = quote(name, safe="")
    coords = _coords(payload.lng, payload.lat, payload.coord_system)
    g_lng, g_lat = coords["GCJ02"]
    b_lng, b_lat = coords["BD09"]

    links: dict[str, dict[str, str]] = {
        # 高德 URI：to=lng,lat,name（经纬度序），coordinate=gaode 表示 GCJ-02
        "amap": {
            "name": _APP_LABELS["amap"],
            "coordSystem": "GCJ02",
            "url": (
                f"https://uri.amap.com/navigation?to={g_lng},{g_lat},{qname}"
                "&mode=car&policy=1&src=flashtrip&coordinate=gaode&callnative=1"
            ),
        },
        # 百度 URI：destination=lat,lng（纬经度序），coord_type=bd09ll
        "baidu": {
            "name": _APP_LABELS["baidu"],
            "coordSystem": "BD09",
            "url": (
                f"https://api.map.baidu.com/direction?destination={b_lat},{b_lng}"
                f"&coord_type=bd09ll&mode=driving&output=html&title={qname}&src=flashtrip"
            ),
        },
        # 腾讯位置服务 URI：tocoord=lat,lng（纬经度序），to=目的地名称
        "tencent": {
            "name": _APP_LABELS["tencent"],
            "coordSystem": "GCJ02",
            "url": (
                f"https://apis.map.qq.com/uri/v1/routeplan?type=drive&to={qname}"
                f"&tocoord={g_lat},{g_lng}&policy=0&referer=flashtrip"
            ),
        },
    }
    return {
        "name": name,
        "target": {"lng": payload.lng, "lat": payload.lat, "coord_system": payload.coord_system},
        "resolved": {
            system: {"lng": pair[0], "lat": pair[1]}
            for system, pair in coords.items()
        },
        "links": links,
    }
