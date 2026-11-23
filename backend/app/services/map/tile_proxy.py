"""瓦片代理核心：子域重试、错误语义分类、上游请求头与内存 LRU 缓存。

设计要点（对应上游实测问题）：
  - key 一律 strip()（天地图 tk 带首尾空格会被 CloudWAF 以 418 拦截）；
  - 请求带普通浏览器 User-Agent 与对应门户 Referer（天地图 WAF 拦截裸请求）；
  - 失败时切换子域重试（天地图 t0-t7，总尝试次数 ≥3 即「首次 + ≥2 次重试」）；
  - 错误不再一律模糊 502：上游鉴权/拦截类 4xx（403 非法 key、418 CloudWAF
    等）映射 400（MAP_TILE_AUTH_FAILED），消息保留上游状态码与简要原因
    （如「天地图返回 403：非法key」）；换子域无意义的确定性鉴权错误立即返回，
    5xx / 网络异常才继续换子域重试，最终仍失败映射 502
    （MAP_TILE_UPSTREAM_ERROR）。
  - 成功瓦片进进程内 LRU + TTL 缓存（容量 512 ≥ 256），key 指纹纳入缓存键
    避免换 key 后命中旧瓦片；错误不缓存。
"""
from __future__ import annotations

import hashlib
import re
import time
from collections import OrderedDict

import httpx

from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger
from app.services.map.credentials import resolve_tile_key
from app.services.map.http_client import TILE_USER_AGENT, upstream_client
from app.services.map.provider_registry import _expand_tiles, get_provider_def

log = get_logger(__name__)

# 鉴权/拦截类 4xx：换子域重试无意义（非法 key 换子域依旧 403），立即返回
_AUTH_STATUS = {401, 403, 407, 418, 451}

# 总尝试次数（首次 + 重试）：子域少于该值则全部尝试
_MAX_ATTEMPTS = 4

_TILE_CACHE: "OrderedDict[tuple, tuple[float, bytes, str]]" = OrderedDict()
_TILE_CACHE_MAX = 512
_TILE_CACHE_TTL_S = 3600.0

# 每个瓦片上游的请求头：UA 模拟普通浏览器；Referer 用对应门户域
_PROVIDER_HEADERS: dict[str, dict[str, str]] = {
    "amap": {
        "User-Agent": TILE_USER_AGENT,
        "Referer": "https://www.amap.com/",
        "Accept": "image/avif,image/webp,image/png,image/*,*/*;q=0.8",
    },
    "tianditu": {
        "User-Agent": TILE_USER_AGENT,
        "Referer": "https://www.tianditu.gov.cn/",
        "Accept": "image/avif,image/webp,image/png,image/*,*/*;q=0.8",
    },
    "mapbox": {
        "User-Agent": TILE_USER_AGENT,
        "Referer": "https://www.mapbox.com/",
        "Accept": "image/avif,image/webp,image/png,image/*,*/*;q=0.8",
    },
}


def reset_tile_cache() -> None:
    """清空进程内瓦片缓存（测试隔离用）。"""
    _TILE_CACHE.clear()


def _key_fingerprint(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12] if key else ""


def _cache_get(cache_key: tuple) -> tuple[bytes, str] | None:
    hit = _TILE_CACHE.get(cache_key)
    if hit is None:
        return None
    stored_at, content, media_type = hit
    if time.monotonic() - stored_at > _TILE_CACHE_TTL_S:
        _TILE_CACHE.pop(cache_key, None)
        return None
    _TILE_CACHE.move_to_end(cache_key)
    return content, media_type


def _cache_put(cache_key: tuple, content: bytes, media_type: str) -> None:
    _TILE_CACHE[cache_key] = (time.monotonic(), content, media_type)
    _TILE_CACHE.move_to_end(cache_key)
    while len(_TILE_CACHE) > _TILE_CACHE_MAX:
        _TILE_CACHE.popitem(last=False)


def _brief_reason(resp: httpx.Response) -> str:
    """提取上游错误简要原因：JSON msg 优先，HTML 拦截页取可读片段，兜底中性文案。"""
    try:
        data = resp.json()
        if isinstance(data, dict):
            for field in ("msg", "message", "info", "error", "detail"):
                value = data.get(field)
                if value:
                    return str(value).strip()[:60]
    except Exception:  # noqa: BLE001  body 非 JSON 属正常情况
        pass
    text = (resp.text or "").strip()
    if text:
        # CloudWAF 418 返回 HTML 拦截页，剥掉标签取首段可读文字
        plain = re.sub(r"<[^>]+>", " ", text)
        plain = re.sub(r"\s+", " ", plain).strip()
        if plain:
            return plain[:40]
    return "上游拒绝访问"


def _validate_coords(z: int, x: int, y: int) -> None:
    """Web Mercator 瓦片坐标边界校验（URL 边界，防止越界/负数拼进上游 URL）。"""
    if not 0 <= z <= 22:
        raise AppError(ErrorCode.VALIDATION, "瓦片层级非法（应在 0-22 之间）")
    span = 1 << z
    if not 0 <= x < span or not 0 <= y < span:
        raise AppError(ErrorCode.VALIDATION, f"瓦片坐标越界（z={z} 时 x/y 应在 0-{span - 1}）")


def fetch_tile(cfg: dict, provider_id: str, z: int, x: int, y: int) -> tuple[bytes, str]:
    """取一张瓦片：缓存命中直返，否则按子域轮询请求上游并分类错误。"""
    _validate_coords(z, x, y)
    defn = get_provider_def(cfg, provider_id)
    template = defn.get("tileUrlTemplate") or ""
    if not template:
        raise AppError(ErrorCode.MAP_PROVIDER_ERROR, "该底图无需瓦片代理，请直接使用 styleUrl")
    # 内部注记层（tianditu-label）等派生 provider 复用母 provider 的凭据
    source_id = str(defn.get("credentialProviderId") or provider_id)
    label = str(defn.get("label") or provider_id)
    key = resolve_tile_key(cfg, source_id).strip()  # 绝不让带空格的 key 进上游 URL
    needs_key = any(token in template for token in ("{key}", "{token}", "{access_token}"))
    if needs_key and not key:
        raise AppError(
            ErrorCode.MAP_TILE_AUTH_FAILED,
            f"{label}尚未配置瓦片密钥，请先在设置中填写",
        )

    tiles = _expand_tiles(defn, key)
    if not tiles:
        raise AppError(ErrorCode.MAP_PROVIDER_ERROR, f"{label}瓦片地址模板无效")

    cache_key = (provider_id, z, x, y, _key_fingerprint(key))
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    headers = _PROVIDER_HEADERS.get(source_id) or _PROVIDER_HEADERS.get(provider_id) or {
        "User-Agent": TILE_USER_AGENT,
    }
    start = (x + y + z) % len(tiles)
    attempts = min(len(tiles), _MAX_ATTEMPTS)
    last_status = 0  # 记录首个非 200 上游状态码，供最终错误消息使用

    for i in range(attempts):
        url = (
            tiles[(start + i) % len(tiles)]
            .replace("{z}", str(z))
            .replace("{x}", str(x))
            .replace("{y}", str(y))
        )
        try:
            with upstream_client() as client:
                resp = client.get(url, headers=headers)
        except Exception as exc:  # noqa: BLE001  异常消息可能带 URL，只记类型
            log.warning("map.tile_request_failed", provider=provider_id, error_type=type(exc).__name__)
            continue
        if resp.status_code == 200 and resp.content:
            media_type = resp.headers.get("content-type") or "image/png"
            _cache_put(cache_key, resp.content, media_type)
            return resp.content, media_type
        if resp.status_code in _AUTH_STATUS:
            # 鉴权/拦截类 4xx：换子域无意义，立即带上游状态码与原因返回
            raise AppError(
                ErrorCode.MAP_TILE_AUTH_FAILED,
                f"{label}返回 {resp.status_code}：{_brief_reason(resp)}",
            )
        # 5xx / 其它 4xx（如个别节点 404）：换子域重试
        last_status = last_status or resp.status_code

    if last_status:
        raise AppError(
            ErrorCode.MAP_TILE_UPSTREAM_ERROR,
            f"{label}瓦片服务不可用（HTTP {last_status}），请稍后重试",
        )
    raise AppError(
        ErrorCode.MAP_TILE_UPSTREAM_ERROR,
        f"{label}瓦片服务连接失败，请稍后重试",
    )
