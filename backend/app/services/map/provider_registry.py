"""地图底图供应商注册表。

约定：
  - 预设元数据（署名 / 审图号 / 坐标系 / 瓦片模板 / styleUrl / 凭据需求）
    一律以 PROVIDER_DEFS 为唯一权威：切换底图即自动带出，前端无需也不得手填；
    向导 / 设置只可写密钥、启用状态与默认样式，绝不覆盖任何技术元数据，
    否则 OpenFreeMap 会被降级成 raster 代理导致空白地图。
  - 前端唯一渲染引擎为 MapLibre GL；OpenFreeMap / Mapbox 直接给矢量 styleUrl，
    高德 / 天地图由本模块构造 raster style 交给 MapLibre 统一渲染。
    百度瓦片坐标系（BD-09）与 Web Mercator 不匹配，实际不可用，已整体删除。
  - 凭据需求拆分为 needsTileKey（瓦片是否需要 key）与 needsServiceKey
    （POI / 路径规划等服务是否需要 key）：高德栅格瓦片实测无 key 返回 200，
    故 needsTileKey=false，未填任何 key 时瓦片仍可用（enabled 保持 true），
    服务能力单列 tilesReady / poiReady / routeReady / servicesReady 下发。
    needsToken 字段保留为兼容标记（install_service 校验与旧前端契约仍读取），
    语义 =「瓦片渲染是否需要凭据」，与 needsTileKey 同值。
  - 多凭据（amap js_key / security_js_code / service_key，tianditu
    browser_tk / server_key）统一加密存于 map.providers[].key_enc，解析见
    credentials.py；list_providers() 只暴露 hasKey / tilesReady 等布尔，
    任何情况下不返回密文或明文、不写日志。
  - 瓦片 URL 中的 {key} 由后端代理注入，绝不把密钥拼进返回给前端的 style。
  - 天地图矢量底图（vec_w）无内置中文注记，配套 cva_w 注记层：预设内置
    tianditu-label（internal，不出现在 /map/providers 列表），瓦片代理端点
    /api/v1/map/tiles/tianditu-label/{z}/{x}/{y} 复用母 provider 的 tk；
    tianditu 的公开 style 双 source 自动叠加注记，前端零改动可用。
  - 个人使用项目：不附带任何境外底图合规提示文案；审图号属服务商公示信息，
    国内一律预置为空字符串，绝不编造具体编号，由前端只读展示中性说明。
"""
from __future__ import annotations

from typing import Any

from app.core.config_store import get_config_store
from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger
from app.services.map.credentials import (
    resolve_tile_key,
    service_key_ready,
    tile_key_ready,
)

log = get_logger(__name__)

# 每个供应商内置完整且确定的元数据；label 只写品牌名，不暴露内部状态；
# 审图号一律留空（属服务商公示信息，绝不编造具体编号）。
PROVIDER_DEFS: list[dict[str, Any]] = [
    {
        # 高德栅格瓦片（webrd0{s}）实测无 key 返回 200 正常图片：
        # needsTileKey=false —— 未填任何 key 时瓦片仍可用；
        # POI / 地理编码 / 路径规划走 Web 服务 key（needsServiceKey=true）。
        "id": "amap",
        "label": "高德地图",
        "styleUrl": None,
        "tileUrlTemplate": (
            "https://webrd0{s}.is.autonavi.com/appmaptile?"
            "lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}"
        ),
        "coordSystem": "GCJ02",
        "attribution": "© 高德地图",
        "auditNumber": "",
        "needsTileKey": False,
        "needsServiceKey": True,
        "needsToken": False,  # 瓦片无需 key：安装向导不得强制用户填写
        "enabled": True,
        "subdomains": ["1", "2", "3", "4"],
    },
    {
        "id": "tianditu",
        "label": "天地图",
        "styleUrl": None,
        "tileUrlTemplate": (
            "https://t{s}.tianditu.gov.cn/DataServer?T=vec_w"
            "&x={x}&y={y}&l={z}&tk={key}"
        ),
        "coordSystem": "CGCS2000",
        "attribution": "© 天地图",
        "auditNumber": "",
        "needsTileKey": True,
        "needsServiceKey": True,
        "needsToken": True,
        "enabled": True,
        "subdomains": ["0", "1", "2", "3", "4", "5", "6", "7"],
        # 矢量底图 vec_w 无中文注记，公开 style 会叠加 cva_w 注记层
        "labelTileProviderId": "tianditu-label",
    },
    {
        # 天地图 cva_w 中文注记层：内部派生 provider，不出现在 /map/providers；
        # 凭据复用 tianditu 名下的 browser_tk（credentialProviderId 重定向）。
        "id": "tianditu-label",
        "label": "天地图注记",
        "styleUrl": None,
        "tileUrlTemplate": (
            "https://t{s}.tianditu.gov.cn/DataServer?T=cva_w"
            "&x={x}&y={y}&l={z}&tk={key}"
        ),
        "coordSystem": "CGCS2000",
        "attribution": "© 天地图",
        "auditNumber": "",
        "needsTileKey": True,
        "needsServiceKey": False,
        "needsToken": True,
        "enabled": True,
        "subdomains": ["0", "1", "2", "3", "4", "5", "6", "7"],
        "internal": True,
        "credentialProviderId": "tianditu",
    },
]

# POI / 地理编码与路径规划各自的实现供应商（服务能力就绪判定用）
POI_PROVIDERS: tuple[str, ...] = ("amap", "tianditu")
ROUTE_PROVIDERS: tuple[str, ...] = ("amap",)


def _resolve_def(provider: str | dict) -> dict[str, Any]:
    """接受 provider id 或 def 字典，返回 def（未知 id 直接报错）。"""
    if isinstance(provider, dict):
        return provider
    for defn in PROVIDER_DEFS:
        if defn["id"] == provider:
            return defn
    raise AppError(ErrorCode.MAP_PROVIDER_ERROR, f"未知地图供应商：{provider}")


def _provider_entries(cfg: dict) -> dict[str, dict]:
    """兼容向导写入的两种结构：{'map': {'providers': {id: {...}}}} 或 list[{id,...}]。

    providers 为 dict / list / None，或 map / cfg 本身非字典时，一律安全返回空表。
    """
    map_cfg = cfg.get("map") if isinstance(cfg, dict) else None
    raw = map_cfg.get("providers") if isinstance(map_cfg, dict) else None
    if isinstance(raw, dict):
        return {str(k): dict(v) for k, v in raw.items() if isinstance(v, dict)}
    if isinstance(raw, list):
        return {
            str(item["id"]): dict(item)
            for item in raw
            if isinstance(item, dict) and item.get("id")
        }
    return {}


def _has_key(entry: dict) -> bool:
    """密文是否已配置（只看字段非空，不解密 —— 列表场景必须零解密失败风险）。"""
    return bool(entry.get("key_enc") or entry.get("api_key_enc") or entry.get("token_enc"))


def get_provider_key(cfg: dict, provider_id: str) -> str:
    """解密供应商瓦片密钥，仅后端内部使用；返回值不得进入响应体或日志。

    多凭据格式下取瓦片专用字段（天地图 browser_tk），
    旧单 key 数据由 credentials 模块迁移到对应字段。
    """
    key = resolve_tile_key(cfg, provider_id)
    if not key:
        raise AppError(ErrorCode.MAP_PROVIDER_ERROR, "该地图供应商尚未配置密钥")
    return key


def _expand_tiles(defn: dict, key: str) -> list[str]:
    """展开 {key} 与 {s} 占位符；MapLibre 用 tiles 数组轮询，不支持 {s}。"""
    template = defn.get("tileUrlTemplate") or ""
    url = (
        template.replace("{key}", key)
        .replace("{token}", key)
        .replace("{access_token}", key)
    )
    subs = defn.get("subdomains") or []
    if "{s}" in url:
        return [url.replace("{s}", s) for s in subs] if subs else [url.replace("{s}", "0")]
    return [url]


def build_raster_style(provider: str | dict, key: str = "") -> dict[str, Any]:
    """构造 MapLibre raster style JSON（含真实上游 URL，仅限后端内部使用）。

    raster 图层作为 layers[0] 置底，业务叠加层由前端在 style.load 后追加其后；
    attribution 必留。无 tileUrlTemplate 的矢量供应商返回引用式 style（前端直接
    setStyle(styleUrl)），避免把 styleUrl 当成 raster 瓦片。天地图底图在此额外
    叠加 cva_w 注记 source（internal 派生 provider 的模板）。
    """
    defn = _resolve_def(provider)
    if not defn.get("tileUrlTemplate"):
        return {
            "version": 8,
            "name": f"FlashTrip · {defn['label']}",
            "sources": {},
            "layers": [],
            "styleUrl": defn.get("styleUrl"),
            "coordSystem": defn["coordSystem"],
        }
    source_id = f"raster-{defn['id']}"
    sources: dict[str, Any] = {
        source_id: {
            "type": "raster",
            "tiles": _expand_tiles(defn, key),
            "tileSize": 256,
            "attribution": defn["attribution"],
        }
    }
    # 首个（也是唯一一个）底图 raster 图层置底，后续叠加层索引更大即在其上
    layers: list[dict[str, Any]] = [
        {
            "id": source_id,
            "type": "raster",
            "source": source_id,
            "paint": {"raster-opacity": 1, "raster-fade-duration": 0},
        }
    ]
    label_pid = defn.get("labelTileProviderId")
    if label_pid:
        label_def = _resolve_def(label_pid)
        label_source = f"raster-{label_pid}"
        sources[label_source] = {
            "type": "raster",
            "tiles": _expand_tiles(label_def, key),
            "tileSize": 256,
            "attribution": label_def["attribution"],
        }
        layers.append({"id": label_source, "type": "raster", "source": label_source})
    return {
        "version": 8,
        "name": f"FlashTrip · {defn['label']}",
        "sources": sources,
        "layers": layers,
        "coordSystem": defn["coordSystem"],
    }


def _public_style(defn: dict) -> dict[str, Any]:
    """返回给前端的 style：瓦片走后端代理路径，URL 中不含任何密钥。"""
    if not defn.get("tileUrlTemplate"):
        return {
            "version": 8,
            "name": f"FlashTrip · {defn['label']}",
            "sources": {},
            "layers": [],
            "styleUrl": defn.get("styleUrl"),
            "coordSystem": defn["coordSystem"],
        }
    source_id = f"raster-{defn['id']}"
    proxy = f"/api/v1/map/tiles/{defn['id']}/{{z}}/{{x}}/{{y}}"
    sources: dict[str, Any] = {
        source_id: {
            "type": "raster",
            "tiles": [proxy],
            "tileSize": 256,
            "attribution": defn["attribution"],
        }
    }
    layers: list[dict[str, Any]] = [{"id": source_id, "type": "raster", "source": source_id}]
    # 天地图：底图 source 之上叠加 cva_w 注记 source（同样走后端代理，无密钥）
    label_pid = defn.get("labelTileProviderId")
    if label_pid:
        label_source = f"raster-{label_pid}"
        sources[label_source] = {
            "type": "raster",
            "tiles": [f"/api/v1/map/tiles/{label_pid}/{{z}}/{{x}}/{{y}}"],
            "tileSize": 256,
            "attribution": defn["attribution"],
        }
        layers.append({"id": label_source, "type": "raster", "source": label_source})
    return {
        "version": 8,
        "name": f"FlashTrip · {defn['label']}",
        "sources": sources,
        "layers": layers,
        "coordSystem": defn["coordSystem"],
    }


def _merged_definitions(cfg: dict) -> list[dict[str, Any]]:
    """预设为唯一权威：只合并运行态（密钥状态 / enabled / default_style）。

    向导或设置页写入的 style_url / tile_url_template / coord_system /
    attribution / audit_number / needs_token / label 一律忽略，绝不覆盖预设，
    保证各 Provider 的底图类型由服务端定义，不会被降级成 raster 代理。
    自定义（非预设）供应商不再支持：切换底图只在预设下拉里进行。
    """
    entries = _provider_entries(cfg)
    definitions: list[dict[str, Any]] = []
    for preset in PROVIDER_DEFS:
        defn = dict(preset)  # 浅拷贝：技术元数据全部保持预设值
        entry = entries.get(defn["id"], {})
        # 仅这三项来自用户配置；任何技术字段都不允许被外部值覆盖
        if isinstance(entry.get("enabled"), bool):
            defn["enabled"] = entry["enabled"]
        default_style = entry.get("default_style") or entry.get("defaultStyle")
        if default_style:
            defn["defaultStyle"] = str(default_style)
        # 密钥只以「是否已配置」布尔并入，绝不下发密文或明文
        defn["hasKey"] = _has_key(entry)
        definitions.append(defn)
    return definitions


def get_provider_def(cfg: dict, provider_id: str) -> dict[str, Any]:
    """取预设为准的供应商定义，供瓦片代理等后端场景使用（含 internal 注记层）。"""
    for defn in _merged_definitions(cfg):
        if defn["id"] == provider_id:
            return defn
    raise AppError(ErrorCode.MAP_PROVIDER_ERROR, f"未知地图供应商：{provider_id}")


def _capability_fields(cfg: dict, defn: dict) -> dict[str, Any]:
    """计算瓦片 / POI / 路径规划的就绪状态（基于多凭据解析，不抛错）。"""
    pid = defn["id"]
    tiles_ready = (not defn.get("needsTileKey")) or tile_key_ready(cfg, pid)
    poi_ready = pid in POI_PROVIDERS and service_key_ready(cfg, pid)
    route_ready = pid in ROUTE_PROVIDERS and service_key_ready(cfg, pid)
    return {
        "tilesReady": tiles_ready,
        "poiReady": poi_ready,
        "routeReady": route_ready,
        "servicesReady": poi_ready or route_ready,
    }


def list_providers(cfg: dict | None = None) -> list[dict[str, Any]]:
    """合并预设与用户配置，输出脱敏后的供应商列表（字段与前端契约保持一致）。

    内部派生 provider（tianditu-label 注记层）不出现在列表里 —— 它由
    tianditu 的公开 style / labelLayer 元数据引用，单独出现反而会干扰下拉。
    """
    cfg = cfg if cfg is not None else get_config_store().load()
    entries = _provider_entries(cfg)
    result: list[dict[str, Any]] = []
    for defn in _merged_definitions(cfg):
        if defn.get("internal"):
            continue
        entry = entries.get(defn["id"], {})
        has_key = bool(defn.get("hasKey"))
        # 瓦片需要 key 而未配置 → 禁用；高德（needsTileKey=false）未填 key
        # 时瓦片仍可用，enabled 不因此置 false，服务就绪度单列字段表达
        if defn.get("needsTileKey") and not tile_key_ready(cfg, defn["id"]):
            enabled = False
        elif isinstance(entry.get("enabled"), bool):
            enabled = entry["enabled"]
        else:
            enabled = bool(defn["enabled"]) or has_key
        # 审图号：config 中用户显式填过则优先，否则用预设（预设恒为空，绝不编造）
        audit_number = str(
            entry.get("audit_number") or entry.get("auditNumber") or defn.get("auditNumber") or ""
        )
        label_pid = defn.get("labelTileProviderId")
        item: dict[str, Any] = {
            "id": defn["id"],
            "label": defn["label"],
            # 瓦片需要 key 的供应商不下发 styleUrl：避免前端直连却拿不到 token
            "styleUrl": None if defn.get("needsTileKey") else defn.get("styleUrl"),
            # 模板里的 {key}/{s} 是占位符而非真实密钥，可安全下发
            "tileUrlTemplate": defn.get("tileUrlTemplate"),
            "coordSystem": defn["coordSystem"],
            "attribution": defn["attribution"],
            "needsToken": defn.get("needsToken", False),
            "needsTileKey": bool(defn.get("needsTileKey")),
            "needsServiceKey": bool(defn.get("needsServiceKey")),
            "auditNumber": audit_number,
            "enabled": enabled,
            "hasKey": has_key,
            # 个人项目不附带任何境外合规提示；保留字段恒为空串以免前端报错
            "complianceNote": "",
            "style": _public_style(defn),
        }
        item.update(_capability_fields(cfg, defn))
        # 天地图注记层元数据：前端可用 tiles URL 直接加 source 叠加
        if label_pid:
            item["labelLayer"] = {
                "providerId": label_pid,
                "tiles": [f"/api/v1/map/tiles/{label_pid}/{{z}}/{{x}}/{{y}}"],
                "coordSystem": "CGCS2000",
            }
        else:
            item["labelLayer"] = None
        result.append(item)
    return result


def map_config(cfg: dict | None = None) -> dict[str, Any]:
    """/map/config：审图号 + 默认底图 + 脱敏供应商列表（不含合规文案）。"""
    cfg = cfg if cfg is not None else get_config_store().load()
    m = cfg.get("map")
    if not isinstance(m, dict):
        m = {}
    providers = list_providers(cfg)
    default_id = str(m.get("default_provider_id") or m.get("defaultProviderId") or "")
    if default_id and not any(p["id"] == default_id and p["enabled"] for p in providers):
        default_id = ""
    if not default_id:
        # 缺省选择无需瓦片密钥的高德底图；其它服务能力可在设置中配置凭据。
        default_id = next((p["id"] for p in providers if p["id"] == "amap" and p["enabled"]), "")
        if not default_id:
            default_id = next((p["id"] for p in providers if p["enabled"]), "")
    return {
        "auditNumber": str(m.get("audit_number") or m.get("auditNumber") or ""),
        "defaultProviderId": default_id,
        "providers": providers,
    }
