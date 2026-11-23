"""地图服务包：坐标转换 / 多凭据 / 供应商注册 / 瓦片代理 / POI / 路线 / 导航。

导入顺序固定为 coord -> credentials -> provider_registry -> http_client ->
tile_proxy -> poi_adapter -> route_service -> navigation，避免包内循环导入
（credentials 不依赖 registry，registry 单向依赖 credentials）。
"""
from __future__ import annotations

from app.services.map.coord import (
    COORD_SYSTEMS,
    from_wgs84,
    to_wgs84,
    transform,
)
from app.services.map.credentials import (
    CREDENTIAL_FIELDS,
    credential_overview,
    get_provider_credentials,
    resolve_service_key,
    resolve_tile_key,
    save_provider_credentials,
)
from app.services.map.provider_registry import (
    PROVIDER_DEFS,
    build_raster_style,
    get_provider_key,
    list_providers,
    map_config,
)
from app.services.map.tile_proxy import fetch_tile
from app.services.map.poi_adapter import geocode, get_poi, search_poi
from app.services.map.route_service import RouteRequest, plan_route
from app.services.map.navigation import NavigationTargetIn, build_navigation_links

__all__ = [
    "COORD_SYSTEMS", "transform", "to_wgs84", "from_wgs84",
    "CREDENTIAL_FIELDS", "credential_overview", "get_provider_credentials",
    "resolve_service_key", "resolve_tile_key", "save_provider_credentials",
    "PROVIDER_DEFS", "list_providers", "build_raster_style",
    "get_provider_key", "map_config",
    "fetch_tile",
    "search_poi", "get_poi", "geocode",
    "RouteRequest", "plan_route",
    "NavigationTargetIn", "build_navigation_links",
]
