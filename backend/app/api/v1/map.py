"""地图 API：脱敏供应商列表、POI 搜索/详情、地理编码、合规配置、瓦片代理。

含 {key} 的瓦片模板经后端代理注入解密后的密钥，前端永远拿不到密钥明文。
路由顺序注意：/map/poi/search 必须位于 /map/poi/{poi_id} 之前。
"""
from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response

from app.api.v1.deps import require_user
from app.core.config_store import get_config_store
from app.core.errors import AppError, ErrorCode
from app.core.response import ok
from app.services.map.poi_adapter import geocode, get_poi, search_poi
from app.services.map.provider_registry import (
    build_raster_style,
    get_provider_def,
    get_provider_key,
    list_providers,
    map_config,
)

router = APIRouter(tags=["map"])


def _rid(request: Request) -> str:
    return getattr(request.state, "request_id", "")


@router.get("/map/providers")
def providers(request: Request, user: Any = Depends(require_user)):
    """脱敏列表：仅 hasKey 布尔，不含密钥。"""
    return ok(list_providers(get_config_store().load()), request_id=_rid(request))


@router.get("/map/config")
def config(request: Request, user: Any = Depends(require_user)):
    """审图号 + 合规文案 + 默认底图。"""
    return ok(map_config(get_config_store().load()), request_id=_rid(request))


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


@router.get("/map/tiles/{provider_id}/{z}/{x}/{y}")
def tile(provider_id: str, z: int, x: int, y: int, request: Request,
         user: Any = Depends(require_user)):
    """后端瓦片代理：仅此处使用解密后的密钥拼上游 URL。"""
    cfg = get_config_store().load()
    defn = get_provider_def(cfg, provider_id)
    template = defn.get("tileUrlTemplate") or ""
    if not template:
        raise AppError(ErrorCode.MAP_PROVIDER_ERROR, "该底图无需瓦片代理，请直接使用 styleUrl")
    needs_key = any(token in template for token in ("{key}", "{token}", "{access_token}"))
    key = get_provider_key(cfg, provider_id) if needs_key else ""
    style = build_raster_style(defn, key)
    tiles = style["sources"][f"raster-{provider_id}"]["tiles"]
    url = tiles[(x + y + z) % len(tiles)].replace("{z}", str(z)).replace("{x}", str(x)).replace("{y}", str(y))
    try:
        with httpx.Client(timeout=10.0, follow_redirects=True) as client:
            resp = client.get(url)
        if resp.status_code != 200:
            raise AppError(ErrorCode.MAP_PROVIDER_ERROR, "底图瓦片获取失败")
        media_type = resp.headers.get("content-type") or "image/png"
        return Response(content=resp.content, media_type=media_type,
                        headers={"Cache-Control": "public, max-age=3600"})
    except AppError:
        raise
    except Exception:  # noqa: BLE001  不回传含密钥的上游异常信息
        raise AppError(ErrorCode.MAP_PROVIDER_ERROR, "底图瓦片连接失败") from None
