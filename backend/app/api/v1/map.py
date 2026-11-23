"""地图 API：脱敏供应商列表、多凭据、POI 搜索/详情、地理编码、路线规划、
导航深链、合规配置、瓦片代理（含天地图 cva_w 注记层）。

含 {key} 的瓦片模板经后端代理注入解密后的密钥，前端永远拿不到密钥明文。
路由顺序注意：/map/poi/search 必须位于 /map/poi/{poi_id} 之前。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response

from app.api.v1.deps import require_permission, require_user
from app.core.config_store import get_config_store
from app.core.response import ok
from app.services.map.credentials import (
    MapCredentialsIn,
    credential_overview,
    save_provider_credentials,
)
from app.services.map.navigation import NavigationTargetIn, build_navigation_links
from app.services.map.poi_adapter import geocode, get_poi, search_poi
from app.services.map.provider_registry import (
    list_providers,
    map_config,
)
from app.services.map.route_service import RouteRequest, plan_route
from app.services.map.tile_proxy import fetch_tile

router = APIRouter(tags=["map"])


def _rid(request: Request) -> str:
    return getattr(request.state, "request_id", "")


@router.get("/map/providers")
def providers(request: Request, user: Any = Depends(require_user)):
    """脱敏列表：仅 hasKey / tilesReady / poiReady 等布尔，不含密钥。"""
    return ok(list_providers(get_config_store().load()), request_id=_rid(request))


@router.get("/map/config")
def config(request: Request, user: Any = Depends(require_user)):
    """审图号 + 合规文案 + 默认底图。"""
    return ok(map_config(get_config_store().load()), request_id=_rid(request))


@router.get("/map/credentials")
def credentials_view(request: Request, user: Any = Depends(require_permission("trip:settings"))):
    """多凭据脱敏视图：每供应商每字段只回是否已配置布尔。"""
    return ok(credential_overview(get_config_store().load()), request_id=_rid(request))


@router.put("/map/credentials")
def credentials_save(payload: MapCredentialsIn, request: Request,
                     user: Any = Depends(require_permission("trip:settings"))):
    """保存结构化多凭据（加密 JSON 写入现有 key_enc，不新增表/字段）。"""
    result = save_provider_credentials(get_config_store(), payload.provider_id, payload.fields)
    return ok(result, request_id=_rid(request))


@router.get("/map/poi/search")
def poi_search(request: Request, q: str = Query(..., min_length=1),
               provider: str = Query(default=""), city: str = Query(default=""),
               user: Any = Depends(require_user)):
    pois = search_poi(q, provider=provider or None, city=city, cfg=get_config_store().load())
    return ok(pois, request_id=_rid(request))


@router.get("/map/geocode")
def geocode_endpoint(request: Request, address: str = Query(..., min_length=1),
                     provider: str = Query(default=""), city: str = Query(default=""),
                     user: Any = Depends(require_user)):
    poi = geocode(address, provider=provider or None, city=city, cfg=get_config_store().load())
    return ok(poi, request_id=_rid(request))


@router.get("/map/poi/{poi_id}")
def poi_detail(poi_id: str, request: Request, provider: str = Query(default=""),
               user: Any = Depends(require_user)):
    return ok(get_poi(poi_id, provider=provider or None), request_id=_rid(request))


@router.post("/map/route")
def route_plan(payload: RouteRequest, request: Request, user: Any = Depends(require_user)):
    """最优路线规划（driving / walking / transit，transit 含公交+高铁）。"""
    return ok(plan_route(payload, cfg=get_config_store().load()), request_id=_rid(request))


@router.post("/map/navigation-links")
def navigation_links(payload: NavigationTargetIn, request: Request,
                     user: Any = Depends(require_user)):
    """五家导航 App 深链（高德/百度/腾讯/Apple/Google，各自坐标系已转换）。"""
    return ok(build_navigation_links(payload), request_id=_rid(request))


@router.get("/map/tiles/{provider_id}/{z}/{x}/{y}")
def tile(provider_id: str, z: int, x: int, y: int, request: Request,
         user: Any = Depends(require_user)):
    """后端瓦片代理：仅此处使用解密后的密钥拼上游 URL（含注记层 tianditu-label）。"""
    content, media_type = fetch_tile(get_config_store().load(), provider_id, z, x, y)
    return Response(
        content=content,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=3600"},
    )
