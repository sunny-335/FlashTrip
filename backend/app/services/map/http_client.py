"""地图上游 HTTP 客户端工厂。

集中构建 httpx.Client，统一超时与默认 UA；测试通过 monkeypatch 本模块的
upstream_client 注入 httpx.MockTransport，保证用例不真实联网。
各上游服务（瓦片 / POI / 路线）对 Referer 的要求不同，Referer 由调用方
按 provider 在请求级传入 headers，不在此处写死。
"""
from __future__ import annotations

import httpx

# 天地图等国内上游的 WAF 会拦截无 UA 的裸请求，必须伪装成普通浏览器
TILE_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def upstream_client(timeout: float = 10.0) -> httpx.Client:
    return httpx.Client(timeout=timeout, follow_redirects=True)
