"""最优路线规划：高德 Web 服务 v3/direction 系列（driving / walking / transit）。

要点：
  - 入参坐标默认 WGS84（前端 POI 统一 WGS84），请求前先转 GCJ-02
    （高德 Web 服务只接受 GCJ-02）；高德返回的折线 / 步骤折线一律转回
    WGS84，供 MapLibre 直接在 WGS84 底图上渲染。
  - 密钥用高德 Web 服务 key（service_key），实测 JS key 调 Web 服务返回
    INVALID_USER_KEY，绝不回退；未配置返回 2009 明确错误。
  - transit 走 /v3/direction/transit/integrated（含公交 + 高铁跨城），
    从 segments 中提取公交线名与高铁班次（railway.name）。
  - 上游 HTTP 走 http_client.upstream_client，测试注入 MockTransport 不联网。
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger
from app.services.map.coord import from_wgs84, to_wgs84
from app.services.map.credentials import resolve_service_key
from app.services.map.http_client import TILE_USER_AGENT, upstream_client

log = get_logger(__name__)

_MODE_URLS: dict[str, str] = {
    "driving": "https://restapi.amap.com/v3/direction/driving",
    "walking": "https://restapi.amap.com/v3/direction/walking",
    # 综合公交：支持跨城公交 + 高铁（含班次信息）
    "transit": "https://restapi.amap.com/v3/direction/transit/integrated",
}

_MODE_LABEL = {"driving": "驾车", "walking": "步行", "transit": "公交"}


class RoutePoint(BaseModel):
    lng: float
    lat: float
    # 入参坐标系：前端存 WGS84，也允许直接传 GCJ02 / BD09 / CGCS2000
    coord_system: str = "WGS84"
    name: str = ""


class RouteRequest(BaseModel):
    origin: RoutePoint
    destination: RoutePoint
    waypoints: list[RoutePoint] = Field(default_factory=list)
    mode: Literal["driving", "walking", "transit"] = "driving"
    # 公交跨城规划可选城市（不填时高德按坐标自动推断）
    city: str = ""
    cityd: str = ""


def _to_gcj02(point: RoutePoint) -> str:
    """入参坐标 → GCJ-02「lng,lat」字符串（高德 Web 服务口径）。"""
    try:
        w_lng, w_lat = to_wgs84(point.lng, point.lat, point.coord_system)
        g_lng, g_lat = from_wgs84(w_lng, w_lat, "GCJ02")
    except ValueError as exc:
        raise AppError(ErrorCode.VALIDATION, f"坐标参数错误：{exc}") from None
    return f"{g_lng:.6f},{g_lat:.6f}"


def _parse_polyline(raw: Any) -> list[list[float]]:
    """高德 polyline「lng,lat;lng,lat」→ WGS84 [[lng, lat], ...]。"""
    if not isinstance(raw, str) or not raw:
        return []
    points: list[list[float]] = []
    for chunk in raw.split(";"):
        parts = chunk.split(",")
        if len(parts) != 2:
            continue
        try:
            g_lng, g_lat = float(parts[0]), float(parts[1])
        except ValueError:
            continue
        w_lng, w_lat = to_wgs84(g_lng, g_lat, "GCJ02")
        points.append([round(w_lng, 7), round(w_lat, 7)])
    return points


def _to_int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _fmt_distance(meters: int) -> str:
    if meters >= 1000:
        return f"{meters / 1000:.1f} 公里"
    return f"{meters} 米"


def _fmt_duration(seconds: int) -> str:
    minutes = max(1, round(seconds / 60))
    if minutes >= 60:
        return f"{minutes // 60} 小时 {minutes % 60} 分钟"
    return f"{minutes} 分钟"


def _request(url: str, params: dict[str, Any]) -> dict:
    """上游请求；异常只记类型，绝不把带 key 的 URL 写进日志/错误。"""
    try:
        with upstream_client() as client:
            resp = client.get(url, params=params, headers={"User-Agent": TILE_USER_AGENT})
        if resp.status_code != 200:
            log.warning("map.route_http_status", status=resp.status_code)
            raise AppError(ErrorCode.MAP_ROUTE_FAILED, "高德路径规划服务暂时不可用")
        return resp.json()
    except AppError:
        raise
    except Exception as exc:  # noqa: BLE001
        log.warning("map.route_request_failed", error_type=type(exc).__name__)
        raise AppError(ErrorCode.MAP_ROUTE_FAILED, "高德路径规划服务连接失败") from None


def _parse_steps(path: dict) -> tuple[list[list[float]], list[dict[str, Any]]]:
    """driving / walking：拼接 steps 折线 + 分段简要说明。"""
    polyline: list[list[float]] = []
    steps: list[dict[str, Any]] = []
    for step in path.get("steps") or []:
        if not isinstance(step, dict):
            continue
        points = _parse_polyline(step.get("polyline"))
        # 相邻 steps 首尾点重复，拼接时去重
        for p in points:
            if not polyline or polyline[-1] != p:
                polyline.append(p)
        steps.append({
            "instruction": str(step.get("instruction") or ""),
            "distance_m": _to_int(step.get("distance")),
            "duration_s": _to_int(step.get("duration")),
            "polyline": points,
        })
    return polyline, steps


def _parse_segments(transit: dict) -> tuple[list[list[float]], list[dict[str, Any]]]:
    """transit：从 segments 提取公交 / 高铁 / 步行分段与可用折线。

    高德 transit/integrated 的 segment 结构为 {bus:{buslines:[...]}, walk:{...}}
    或跨城 {railway:{name, trip, ...}, walk:{...}}；railway.name 即高铁班次。
    """
    polyline: list[list[float]] = []
    segments: list[dict[str, Any]] = []
    for seg in transit.get("segments") or []:
        if not isinstance(seg, dict):
            continue
        points = _parse_polyline(seg.get("polyline"))
        for p in points:
            if not polyline or polyline[-1] != p:
                polyline.append(p)

        railway = seg.get("railway")
        bus = seg.get("bus")
        walk = seg.get("walk")
        if isinstance(railway, dict) and railway:
            # 高铁 / 火车段：name 常含车次（如「G101 高速动车」）
            segments.append({
                "type": "railway",
                "name": str(railway.get("name") or railway.get("trip") or "铁路"),
                "instruction": str(railway.get("instruction") or ""),
                "departure": str((railway.get("departure_stop") or {}).get("name") or ""),
                "arrival": str((railway.get("arrival_stop") or {}).get("name") or ""),
                "duration_s": _to_int(railway.get("duration")),
                "distance_m": _to_int(railway.get("distance")),
            })
        elif isinstance(bus, dict) and bus:
            lines = bus.get("buslines") or []
            line = lines[0] if lines and isinstance(lines[0], dict) else {}
            segments.append({
                "type": "bus",
                "name": str(line.get("name") or "公交线路"),
                "instruction": str(bus.get("instruction") or ""),
                "departure": str((line.get("departure_stop") or {}).get("name") or ""),
                "arrival": str((line.get("arrival_stop") or {}).get("name") or ""),
                "duration_s": _to_int(line.get("duration")),
                "distance_m": _to_int(bus.get("distance")),
            })
            for extra in lines:
                if isinstance(extra, dict):
                    for p in _parse_polyline(extra.get("polyline")):
                        if not polyline or polyline[-1] != p:
                            polyline.append(p)
        elif isinstance(walk, dict):
            segments.append({
                "type": "walk",
                "name": "步行",
                "instruction": str(walk.get("instruction") or ""),
                "duration_s": _to_int(walk.get("duration")),
                "distance_m": _to_int(walk.get("distance")),
            })
    return polyline, segments


def plan_route(payload: RouteRequest, cfg: dict) -> dict:
    """规划最优路线并返回 WGS84 折线、总时长/距离、分段说明。"""
    key = resolve_service_key(cfg, "amap")
    if not key:
        raise AppError(
            ErrorCode.MAP_SERVICE_KEY_MISSING,
            "未配置高德 Web 服务 key，无法规划路线，请先在设置中填写",
        )
    url = _MODE_URLS[payload.mode]
    params: dict[str, Any] = {
        "key": key,
        "origin": _to_gcj02(payload.origin),
        "destination": _to_gcj02(payload.destination),
        "output": "json",
    }
    if payload.mode == "driving":
        params["extensions"] = "base"
        if payload.waypoints:
            # 高德驾车途经点：竖线分隔，最多 16 个
            params["waypoints"] = "|".join(_to_gcj02(p) for p in payload.waypoints[:16])
    elif payload.mode == "transit":
        params["strategy"] = 0  # 推荐模式（含高铁跨城）
        if payload.city:
            params["city"] = payload.city
        if payload.cityd:
            params["cityd"] = payload.cityd

    data = _request(url, params)
    if str(data.get("status")) != "1":
        info = str(data.get("info") or "")
        raise AppError(ErrorCode.MAP_ROUTE_FAILED, f"高德路径规划失败：{info or '未找到可行路线'}")
    route = data.get("route") or {}

    if payload.mode in ("driving", "walking"):
        paths = route.get("paths") or []
        if not paths or not isinstance(paths[0], dict):
            raise AppError(ErrorCode.MAP_ROUTE_FAILED, "高德未返回可用路线")
        path = paths[0]
        distance_m = _to_int(path.get("distance"))
        duration_s = _to_int(path.get("duration"))
        polyline, steps = _parse_steps(path)
        segments: list[dict[str, Any]] = []
    else:
        transits = route.get("transits") or []
        if not transits or not isinstance(transits[0], dict):
            raise AppError(ErrorCode.MAP_ROUTE_FAILED, "高德未返回可用公交/高铁方案")
        transit = transits[0]
        distance_m = _to_int(transit.get("distance"))
        duration_s = _to_int(transit.get("duration"))
        polyline, segments = _parse_segments(transit)
        steps = []

    return {
        "provider": "amap",
        "mode": payload.mode,
        "mode_label": _MODE_LABEL[payload.mode],
        "distance_m": distance_m,
        "duration_s": duration_s,
        "distance_text": _fmt_distance(distance_m),
        "duration_text": _fmt_duration(duration_s),
        "polyline": polyline,
        "coord_system": "WGS84",
        "steps": steps,
        "segments": segments,
        "summary": (
            f"{_MODE_LABEL[payload.mode]}约 {_fmt_distance(distance_m)} / "
            f"{_fmt_duration(duration_s)}"
        ),
    }
