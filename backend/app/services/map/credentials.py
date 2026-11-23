"""地图供应商多凭据模型：结构化多字段凭据的存储 / 解析 / 兼容迁移。

存储约定（沿用现有机制，不新建表、不加迁移）：
  - 每个供应商仍只有一个加密字段 map.providers[].key_enc（config.json 权威 +
    DB app_config 镜像 + read_config_sanitized 脱敏 + rotate_secret 轮换，
    全部沿用现有链路，install_service / settings 无需感知本模块）。
  - 多凭据 = 把明文字段字典序列化为 JSON 后整体 encrypt 进 key_enc：
    {"js_key": "...", "security_js_code": "...", "service_key": "..."}。
    rotate_secret 对 key_enc 做「解密 → 新密钥重加密」，内容透明，天然兼容。
  - 旧数据兼容：解密结果不是 JSON（单 key 明文）时按 LEGACY_FIELD 迁移映射
    —— amap→service_key（Web 服务 key 是历史场景的主要填法，实测 JS key 调
    Web 服务返回 INVALID_USER_KEY），tianditu→browser_tk（浏览器端 tk 正是
    瓦片底图用途）。新旧格式在 get_provider_credentials() 统一归一为 dict。
  - 所有字段值入库前一律 strip()：天地图实测 tk 带首尾空格会被 CloudWAF
    以 418 拦截，绝不让脏值进入上游 URL。
  - 服务 key 允许在专用字段缺失时回退到同供应商其它凭据（天地图的 tk 常常
    浏览器/服务端两用）；高德 JS key 实测不能调 Web 服务，绝不回退。
"""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger
from app.core.security import decrypt, encrypt

log = get_logger(__name__)

# 各供应商支持的结构化凭据字段（label 供设置页展示，脱敏输出不含明文）
CREDENTIAL_FIELDS: dict[str, dict[str, str]] = {
    "amap": {
        "js_key": "JS API Key（前端 JS SDK 加载用）",
        "security_js_code": "安全密钥 securityJscode（配合 JS Key）",
        "service_key": "Web 服务 Key（POI / 地理编码 / 路径规划）",
    },
    "tianditu": {
        "browser_tk": "浏览器端 tk（瓦片底图 / 注记层）",
        "server_key": "服务端 key（POI / 地理编码）",
    },
    "mapbox": {
        "tile_key": "Access Token（栅格瓦片）",
    },
}

# 旧「单 key_enc」数据的迁移映射：旧值视作该字段
LEGACY_FIELD: dict[str, str] = {
    "amap": "service_key",
    "tianditu": "browser_tk",
    "mapbox": "tile_key",
}

# 瓦片代理取 key 的主字段（amap 瓦片无需 key，不在表内）
_TILE_KEY_FIELD: dict[str, str] = {
    "tianditu": "browser_tk",
    "mapbox": "tile_key",
}

# 服务端（POI / 地理编码 / 路线）取 key 的主字段
_SERVICE_KEY_FIELD: dict[str, str] = {
    "amap": "service_key",
    "tianditu": "server_key",
}

# 主字段为空时允许回退的字段（天地图 tk 常浏览器/服务端两用；
# 高德 JS key 实测调 Web 服务报 INVALID_USER_KEY，不做回退）
_TILE_KEY_FALLBACK: dict[str, str] = {
    "tianditu": "server_key",
}
_SERVICE_KEY_FALLBACK: dict[str, str] = {
    "tianditu": "browser_tk",
}

# 注记层等派生 provider 复用母 provider 的凭据存储
_CREDENTIAL_SOURCE: dict[str, str] = {
    "tianditu-label": "tianditu",
}


class MapCredentialsIn(BaseModel):
    """PUT /map/credentials 请求体：字段值非空则覆盖，空字符串表示清除该字段。"""

    provider_id: str = Field(min_length=1, max_length=64)
    fields: dict[str, str] = Field(default_factory=dict)


def credential_source_id(provider_id: str) -> str:
    """凭据实际存放的 provider id（tianditu-label 的 tk 存在 tianditu 名下）。"""
    return _CREDENTIAL_SOURCE.get(provider_id, provider_id)


def _provider_entries(cfg: dict) -> dict[str, dict]:
    """兼容 map.providers 的 dict / list 两种结构（与 registry 保持同一口径）。"""
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


def _parse_credentials(plain: str, provider_id: str) -> dict[str, str]:
    """把解密后的明文解析为字段字典：JSON 优先，否则按旧单 key 迁移。"""
    plain = (plain or "").strip()
    if not plain:
        return {}
    if plain.startswith("{"):
        try:
            data = json.loads(plain)
        except ValueError:
            data = None
        if isinstance(data, dict):
            return {
                str(k): str(v).strip()
                for k, v in data.items()
                if str(v or "").strip()
            }
        # JSON 非法（历史脏数据）按旧单 key 迁移兜底，绝不静默丢弃
    field = LEGACY_FIELD.get(provider_id, "tile_key")
    return {field: plain}


def get_provider_credentials(cfg: dict, provider_id: str) -> dict[str, str]:
    """解密并归一化某供应商的全部凭据；仅后端内部使用，返回值不得进入响应体。

    解密失败（主密钥更换等）抛错，提示用户重新填写，绝不把密文或异常写日志。
    """
    source = credential_source_id(provider_id)
    entry = _provider_entries(cfg).get(source, {})
    enc = entry.get("key_enc") or entry.get("api_key_enc") or entry.get("token_enc") or ""
    if not str(enc):
        return {}
    try:
        plain = decrypt(str(enc))
    except Exception:  # noqa: BLE001  解密失败不得泄露密文/异常细节
        log.warning("map.credentials_decrypt_failed", provider=source)
        raise AppError(
            ErrorCode.MAP_PROVIDER_ERROR, "地图密钥无法解密，请在设置中重新填写"
        ) from None
    return _parse_credentials(plain, source)


def credentials_snapshot(cfg: dict, provider_id: str) -> dict[str, str]:
    """同 get_provider_credentials，但任何失败都返回空 dict（用于列表/展示场景）。"""
    try:
        return get_provider_credentials(cfg, provider_id)
    except AppError:
        return {}


def _resolve_field(provider_id: str, cred: dict[str, str], table: dict, fallback: dict) -> str:
    """按「主字段 → 白名单回退字段」顺序取非空值。"""
    source = credential_source_id(provider_id)
    main = table.get(source)
    if main:
        value = cred.get(main, "")
        if value:
            return value
    backup = fallback.get(source)
    if backup:
        return cred.get(backup, "")
    return ""


def resolve_tile_key(cfg: dict, provider_id: str) -> str:
    """取瓦片代理用的 key（已 strip）；amap 瓦片无需 key，返回空串。"""
    cred = get_provider_credentials(cfg, provider_id)
    return _resolve_field(provider_id, cred, _TILE_KEY_FIELD, _TILE_KEY_FALLBACK)


def resolve_service_key(cfg: dict, provider_id: str) -> str:
    """取 POI / 地理编码 / 路线等服务端 key（已 strip）。"""
    cred = get_provider_credentials(cfg, provider_id)
    return _resolve_field(provider_id, cred, _SERVICE_KEY_FIELD, _SERVICE_KEY_FALLBACK)


def service_key_ready(cfg: dict, provider_id: str) -> bool:
    """服务 key 是否就绪（列表/选择场景用，不抛错）。"""
    cred = credentials_snapshot(cfg, provider_id)
    return bool(_resolve_field(provider_id, cred, _SERVICE_KEY_FIELD, _SERVICE_KEY_FALLBACK))


def tile_key_ready(cfg: dict, provider_id: str) -> bool:
    """瓦片 key 是否就绪（列表场景用，不抛错）。"""
    cred = credentials_snapshot(cfg, provider_id)
    source = credential_source_id(provider_id)
    main = _TILE_KEY_FIELD.get(source)
    return bool(main and cred.get(main))


def credential_overview(cfg: dict) -> dict[str, Any]:
    """GET /map/credentials：每供应商每字段只回「是否已配置」布尔，不含明文/密文。"""
    providers: dict[str, dict[str, Any]] = {}
    for provider_id, fields in CREDENTIAL_FIELDS.items():
        cred = credentials_snapshot(cfg, provider_id)
        providers[provider_id] = {
            "fields": {name: bool(cred.get(name)) for name in fields},
            "labels": dict(fields),
        }
    return {"providers": providers}


def save_provider_credentials(store: Any, provider_id: str, fields: dict[str, str]) -> dict[str, Any]:
    """保存结构化凭据：merge 进现有 JSON 后整体加密写入 key_enc。

    store 为 ConfigStore 实例（沿用 config.json 权威 + DB 镜像写回机制）。
    旧写入链路（PUT /settings 的单 key）提交非空 key 时会覆盖 key_enc，
    多字段信息退化为旧单 key 格式 —— 本模块的解析对两种格式都兼容。
    """
    provider_id = (provider_id or "").strip()
    if provider_id not in CREDENTIAL_FIELDS:
        raise AppError(
            ErrorCode.MAP_PROVIDER_ERROR, f"该供应商不支持凭据配置：{provider_id}"
        )
    allowed = CREDENTIAL_FIELDS[provider_id]
    unknown = [name for name in fields if name not in allowed]
    if unknown:
        raise AppError(
            ErrorCode.VALIDATION,
            f"供应商 {provider_id} 不支持的凭据字段：{', '.join(unknown)}",
        )

    cfg = store.load()
    entries = _provider_entries(cfg)
    entry = dict(entries.get(provider_id, {}))
    cred = credentials_snapshot(cfg, provider_id)
    for name, value in (fields or {}).items():
        value = (value or "").strip()
        if value:
            cred[name] = value
        else:
            cred.pop(name, None)  # 空字符串 = 显式清除该字段

    if cred:
        entry["key_enc"] = encrypt(json.dumps(cred, ensure_ascii=False))
    else:
        entry["key_enc"] = ""  # 全部清除
    entry["id"] = provider_id
    # entry 中残留的旧手填技术字段顺手剥掉（预设才是唯一权威）
    for legacy in ("style_url", "tile_url_template", "coord_system", "attribution", "needs_token"):
        entry.pop(legacy, None)

    map_cfg = cfg.get("map") if isinstance(cfg.get("map"), dict) else {}
    raw = map_cfg.get("providers")
    if isinstance(raw, list):
        # 保持 list 结构：命中则原位替换，否则追加
        replaced = False
        for i, item in enumerate(raw):
            if isinstance(item, dict) and str(item.get("id")) == provider_id:
                raw[i] = entry
                replaced = True
                break
        if not replaced:
            raw.append(entry)
    else:
        # dict / None / 其它：统一落到 dict 结构（读取侧两种都兼容）
        target = dict(raw) if isinstance(raw, dict) else {}
        target[provider_id] = entry
        map_cfg["providers"] = target
    cfg["map"] = map_cfg
    store.save(cfg)

    # 脱敏回执：只回布尔，绝不回明文或密文
    return {
        "provider_id": provider_id,
        "fields": {name: bool(cred.get(name)) for name in allowed},
    }
