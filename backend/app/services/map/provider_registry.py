"""地图底图供应商注册表。

约定：
  - 前端唯一渲染引擎为 MapLibre GL；OpenFreeMap / Mapbox 直接给矢量 styleUrl，
    高德 / 百度 / 天地图由本模块构造 raster style 交给 MapLibre 统一渲染。
  - 密钥（key_enc / api_key_enc）只在后端用 decrypt() 解出；list_providers()
    只暴露 hasKey 布尔，任何情况下不返回密文或明文、不写日志。
  - 瓦片 URL 中的 {key} 由后端代理注入，绝不把密钥拼进返回给前端的 style。
"""
from __future__ import annotations

from typing import Any

from app.core.config_store import get_config_store
from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger
from app.core.security import decrypt

log = get_logger(__name__)

_OFM_BASE = "https://tiles.openfreemap.org/styles"
_OFM_ATTR = "© OpenFreeMap · © OpenMapTiles · © OpenStreetMap contributors"
_COMPLIANCE = (
    "境外底图数据源仅建议用于境外行程或个人自用；面向境内公众服务请使用"
    "带审图号的国内合规底图，并以主管部门审核结论为准。本系统不声称已完成地图合规备案。"
)

PROVIDER_DEFS: list[dict[str, Any]] = [
    *[
        {
            "id": f"openfreemap-{style}",
            "label": f"OpenFreeMap · {label}",
            "styleUrl": f"{_OFM_BASE}/{style}",
            "tileUrlTemplate": None,
            "coordSystem": "WGS84",
            "attribution": _OFM_ATTR,
            "needsToken": False,
            "auditNumber": "",
            "enabled": True,
        }
        for style, label in (
            ("liberty", "Liberty"), ("bright", "Bright"), ("positron", "Positron"),
            ("dark", "Dark"), ("fiord", "Fiord"), ("3d", "3D"),
        )
    ],
    {
        "id": "mapbox",
        "label": "Mapbox（需 Token）",
        "styleUrl": "mapbox://styles/mapbox/streets-v12",
        "tileUrlTemplate": (
            "https://api.mapbox.com/styles/v1/mapbox/streets-v12/tiles/256/"
            "{z}/{x}/{y}@2x?access_token={key}"
        ),
        "coordSystem": "WGS84",
        "attribution": "© Mapbox · © OpenStreetMap",
        "needsToken": True,
        "auditNumber": "",
        "enabled": False,  # 未填 token 时始终 disabled
        "subdomains": [],
    },
    {
        "id": "amap",
        "label": "高德地图",
        "styleUrl": None,
        "tileUrlTemplate": (
            "https://webrd0{s}.is.autonavi.com/appmaptile?"
            "lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}"
        ),
        "coordSystem": "GCJ02",
        "attribution": "© 高德地图 AutoNavi",
        "needsToken": True,
        "auditNumber": "",
        "enabled": True,
        "subdomains": ["1", "2", "3", "4"],
    },
    {
        "id": "baidu",
        "label": "百度地图",
        "styleUrl": None,
        "tileUrlTemplate": (
            "https://maponline{s}.bdimg.com/tile/?qt=tile&x={x}&y={y}&z={z}"
            "&styles=pl&scaler=1&udt=20240101"
        ),
        "coordSystem": "BD09",
        "attribution": "© 百度地图 Baidu",
        "needsToken": True,
        "auditNumber": "",
        "enabled": True,
        "subdomains": ["0", "1", "2", "3"],
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
        "attribution": "© 天地图 Tianditu",
        "needsToken": True,
        "auditNumber": "",
        "enabled": True,
        "subdomains": ["0", "1", "2", "3", "4", "5", "6", "7"],
    },
]


def _resolve_def(provider: str | dict) -> dict[str, Any]:
    """接受 provider id 或 def 字典，返回 def（未知 id 直接报错）。"""
    if isinstance(provider, dict):
        return provider
    for defn in PROVIDER_DEFS:
        if defn["id"] == provider:
            return defn
    raise AppError(ErrorCode.MAP_PROVIDER_ERROR, f"未知地图供应商：{provider}")


def _provider_entries(cfg: dict) -> dict[str, dict]:
    """兼容向导写入的两种结构：{'map': {'providers': {id: {...}}}} 或 list[{id,...}]。"""
    raw = (cfg.get("map") or {}).get("providers")
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
    return bool(entry.get("key_enc") or entry.get("api_key_enc") or entry.get("token_enc"))


def get_provider_key(cfg: dict, provider_id: str) -> str:
    """解密供应商密钥，仅后端内部使用；返回值不得进入响应体或日志。"""
    entry = _provider_entries(cfg).get(provider_id, {})
    enc = entry.get("key_enc") or entry.get("api_key_enc") or entry.get("token_enc") or ""
    if not enc:
        raise AppError(ErrorCode.MAP_PROVIDER_ERROR, "该地图供应商尚未配置密钥")
    try:
        return decrypt(str(enc))
    except Exception:  # noqa: BLE001  解密失败不得把密文/异常 URL 写进日志
        log.warning("map.key_decrypt_failed", provider=provider_id)
        raise AppError(ErrorCode.MAP_PROVIDER_ERROR, "地图密钥无法解密，请在设置中重新填写") from None


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
    """构造 MapLibre raster style JSON。

    raster 图层作为 layers[0] 置底，业务叠加层由前端在 style.load 后追加其后；
    attribution 必留。无 tileUrlTemplate 的矢量供应商返回引用式 style（前端直接
    setStyle(styleUrl)），避免把 styleUrl 当成 raster 瓦片。
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
    return {
        "version": 8,
        "name": f"FlashTrip · {defn['label']}",
        "sources": {
            source_id: {
                "type": "raster",
                "tiles": _expand_tiles(defn, key),
                "tileSize": 256,
                "attribution": defn["attribution"],
            }
        },
        # 首个（也是唯一一个）底图 raster 图层置底，后续叠加层索引更大即在其上
        "layers": [
            {
                "id": source_id,
                "type": "raster",
                "source": source_id,
                "paint": {"raster-opacity": 1, "raster-fade-duration": 0},
            }
        ],
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
    return {
        "version": 8,
        "name": f"FlashTrip · {defn['label']}",
        "sources": {
            source_id: {
                "type": "raster",
                "tiles": [proxy],
                "tileSize": 256,
                "attribution": defn["attribution"],
            }
        },
        "layers": [{"id": source_id, "type": "raster", "source": source_id}],
        "coordSystem": defn["coordSystem"],
    }


def _custom_def(provider_id: str, entry: dict) -> dict[str, Any]:
    """向导里手填的、不在预设表中的供应商（字段名兼容 snake_case / camelCase）。"""
    return {
        "id": provider_id,
        "label": str(entry.get("label") or entry.get("name") or provider_id),
        "styleUrl": entry.get("style_url") or entry.get("styleUrl"),
        "tileUrlTemplate": entry.get("tile_url_template") or entry.get("tileUrlTemplate"),
        "coordSystem": str(entry.get("coord_system") or entry.get("coordSystem") or "WGS84"),
        "attribution": str(entry.get("attribution") or ""),
        "needsToken": bool(entry.get("needs_token", entry.get("needsToken", False))),
        "auditNumber": str(entry.get("audit_number") or ""),
        "enabled": bool(entry.get("enabled", True)),
        "subdomains": [],
    }


def _merged_definitions(cfg: dict) -> list[dict[str, Any]]:
    """预设 + 向导自定义供应商，并把向导的覆盖字段合并进 def。"""
    entries = _provider_entries(cfg)
    known = {defn["id"] for defn in PROVIDER_DEFS}
    definitions: list[dict[str, Any]] = [dict(defn) for defn in PROVIDER_DEFS]
    definitions.extend(
        _custom_def(pid, entry) for pid, entry in entries.items() if pid not in known
    )
    for defn in definitions:
        entry = entries.get(defn["id"], {})
        style_url = entry.get("style_url") or entry.get("styleUrl")
        if style_url:
            defn["styleUrl"] = str(style_url)
        tile_url = entry.get("tile_url_template") or entry.get("tileUrlTemplate")
        if tile_url:
            defn["tileUrlTemplate"] = str(tile_url)
        coord = entry.get("coord_system") or entry.get("coordSystem")
        if coord:
            defn["coordSystem"] = str(coord)
        if entry.get("attribution"):
            defn["attribution"] = str(entry["attribution"])
        # 只收紧不放松：预设里 needsToken=True 属于技术事实，
        # 向导未显式声明时不得把它降为 False 而绕过密钥校验
        if entry.get("needs_token") or entry.get("needsToken"):
            defn["needsToken"] = True
    return definitions


def get_provider_def(cfg: dict, provider_id: str) -> dict[str, Any]:
    """取合并后的供应商定义（含向导自定义项），供瓦片代理等后端场景使用。"""
    for defn in _merged_definitions(cfg):
        if defn["id"] == provider_id:
            return defn
    raise AppError(ErrorCode.MAP_PROVIDER_ERROR, f"未知地图供应商：{provider_id}")


def list_providers(cfg: dict | None = None) -> list[dict[str, Any]]:
    """合并向导配置与预设，输出脱敏后的供应商列表（不含任何密钥）。"""
    cfg = cfg if cfg is not None else get_config_store().load()
    entries = _provider_entries(cfg)
    result: list[dict[str, Any]] = []
    for defn in _merged_definitions(cfg):
        entry = entries.get(defn["id"], {})
        has_key = _has_key(entry)
        if defn["needsToken"] and not has_key:
            enabled = False
        elif isinstance(entry.get("enabled"), bool):
            enabled = entry["enabled"]
        else:
            enabled = bool(defn["enabled"]) or has_key
        audit_number = str(
            entry.get("audit_number") or entry.get("auditNumber") or defn.get("auditNumber") or ""
        )
        result.append(
            {
                "id": defn["id"],
                "label": defn["label"],
                # 需要 token 的供应商不下发 styleUrl：避免前端直连 mapbox:// 却拿不到 token
                "styleUrl": None if defn["needsToken"] else defn.get("styleUrl"),
                # 模板里的 {key}/{s} 是占位符而非真实密钥，可安全下发
                "tileUrlTemplate": defn.get("tileUrlTemplate"),
                "coordSystem": defn["coordSystem"],
                "attribution": defn["attribution"],
                "needsToken": defn["needsToken"],
                "auditNumber": audit_number,
                "enabled": enabled,
                "hasKey": has_key,
                "complianceNote": _COMPLIANCE if defn["coordSystem"] == "WGS84" else "",
                "style": _public_style(defn),
            }
        )
    return result


def map_config(cfg: dict | None = None) -> dict[str, Any]:
    """/map/config：审图号 + 合规文案 + 默认底图。"""
    cfg = cfg if cfg is not None else get_config_store().load()
    m = cfg.get("map") or {}
    providers = list_providers(cfg)
    default_id = str(m.get("default_provider_id") or "")
    if default_id and not any(p["id"] == default_id and p["enabled"] for p in providers):
        default_id = ""
    if not default_id:
        # 默认优先已启用的国内合规底图，其次 OpenFreeMap
        domestic = next((p["id"] for p in providers if p["enabled"] and p["coordSystem"] != "WGS84"), "")
        default_id = domestic or next((p["id"] for p in providers if p["enabled"]), "openfreemap-liberty")
    return {
        "auditNumber": str(m.get("audit_number") or m.get("auditNumber") or ""),
        "complianceNote": _COMPLIANCE,
        "defaultProviderId": default_id,
        "providers": providers,
    }


COMPLIANCE_NOTE = _COMPLIANCE
