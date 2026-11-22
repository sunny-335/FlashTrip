"""地图服务包：坐标转换 / 供应商注册 / POI 适配。

导入顺序固定为 coord -> provider_registry -> poi_adapter，避免包内循环导入。
"""
from __future__ import annotations

from app.services.map.coord import (
    COORD_SYSTEMS,
    from_wgs84,
    to_wgs84,
    transform,
)
from app.services.map.provider_registry import (
    PROVIDER_DEFS,
    build_raster_style,
    get_provider_key,
    list_providers,
    map_config,
)
from app.services.map.poi_adapter import geocode, get_poi, search_poi

__all__ = [
    "COORD_SYSTEMS", "transform", "to_wgs84", "from_wgs84",
    "PROVIDER_DEFS", "list_providers", "build_raster_style",
    "get_provider_key", "map_config",
    "search_poi", "get_poi", "geocode",
]
