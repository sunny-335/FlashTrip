"""地图服务测试：瓦片错误语义 / 重试 / 缓存、多凭据端点、POI/geocode、
路线规划、导航深链、百度删除回归。

所有上游网络调用一律 monkeypatch 为 httpx.MockTransport，绝不真实联网。
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from urllib.parse import quote

import httpx
import pytest

from app.api.v1 import deps
from app.core import config_store as cs
from app.core.config_store import ConfigStore
from app.core.security import decrypt, encrypt
from app.services.map import poi_adapter, route_service, tile_proxy


# ---------------------------------------------------------------- 基础设施

@pytest.fixture(autouse=True)
def _reset_caches():
    """瓦片 / POI 进程内缓存按用例隔离，避免跨用例命中。"""
    tile_proxy.reset_tile_cache()
    poi_adapter._POI_CACHE.clear()
    yield
    tile_proxy.reset_tile_cache()
    poi_adapter._POI_CACHE.clear()


@pytest.fixture()
def map_api(client, monkeypatch, tmp_path):
    """覆盖登录用户 + 隔离 config.json，返回 (client, install)。"""
    fake = SimpleNamespace(id="u-1", role="owner", must_set_password=False)
    monkeypatch.setitem(client.app.dependency_overrides, deps.require_user, lambda: fake)
    store = ConfigStore(path=tmp_path / "config.json")
    store.save({"installed": True, "secret_key": "unit-test-secret", "map": {"providers": []}})
    monkeypatch.setattr(cs, "_store", store)

    def install(providers: list[dict]) -> None:
        store.save({
            "installed": True,
            "secret_key": "unit-test-secret",
            "map": {"providers": providers},
        })

    return client, install


def _entry(provider_id: str, **fields: str) -> dict:
    """构造多凭据条目（加密 JSON 存 key_enc）。"""
    return {"id": provider_id, "key_enc": encrypt(json.dumps(fields, ensure_ascii=False))}


def _mock_upstream(monkeypatch, module, handler) -> list[httpx.Request]:
    calls: list[httpx.Request] = []

    def _wrapped(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)

    transport = httpx.MockTransport(_wrapped)

    def _client(timeout: float = 10.0) -> httpx.Client:
        return httpx.Client(transport=transport, timeout=timeout, follow_redirects=True)

    monkeypatch.setattr(module, "upstream_client", _client)
    return calls


# ---------------------------------------------------------------- 瓦片代理

def test_tile_ok_strips_key_and_sends_ua_referer(map_api, monkeypatch):
    client, install = map_api
    install([_entry("tianditu", browser_tk=" tdt-key ")])  # 带首尾空格
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["tk"] = request.url.params.get("tk", "")
        seen["ua"] = request.headers.get("user-agent", "")
        seen["referer"] = request.headers.get("referer", "")
        return httpx.Response(200, content=b"\x89PNGdata", headers={"content-type": "image/png"})

    _mock_upstream(monkeypatch, tile_proxy, handler)
    resp = client.get("/api/v1/map/tiles/tianditu/3/6/3")

    assert resp.status_code == 200, resp.text
    assert resp.content == b"\x89PNGdata"
    assert "image/png" in resp.headers["content-type"]
    assert seen["tk"] == "tdt-key"          # 空格已 strip
    assert "Mozilla" in seen["ua"]           # 普通浏览器 UA
    assert seen["referer"] == "https://www.tianditu.gov.cn/"


def test_tile_403_illegal_key_maps_to_400_with_reason(map_api, monkeypatch):
    client, install = map_api
    install([_entry("tianditu", browser_tk="bad-key")])
    calls = _mock_upstream(
        monkeypatch, tile_proxy,
        lambda request: httpx.Response(403, json={"msg": "非法key", "code": 301001}),
    )
    resp = client.get("/api/v1/map/tiles/tianditu/3/6/3")

    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == 2007
    assert "403" in body["message"] and "非法key" in body["message"]
    # 鉴权类确定性错误不换子域重试
    assert len(calls) == 1


def test_tile_418_cloudwaf_block_keeps_upstream_status(map_api, monkeypatch):
    client, install = map_api
    install([_entry("tianditu", browser_tk="bad-key")])
    _mock_upstream(
        monkeypatch, tile_proxy,
        lambda request: httpx.Response(418, text="<html><body>访问被拦截</body></html>"),
    )
    resp = client.get("/api/v1/map/tiles/tianditu/3/6/3")

    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == 2007
    assert "418" in body["message"] and "访问被拦截" in body["message"]


def test_tile_retries_across_subdomains_on_5xx(map_api, monkeypatch):
    client, install = map_api
    install([_entry("tianditu", browser_tk="tdt-key")])
    statuses = iter([503, 503, 200])

    def handler(request: httpx.Request) -> httpx.Response:
        status = next(statuses)
        if status == 200:
            return httpx.Response(200, content=b"PNG", headers={"content-type": "image/png"})
        return httpx.Response(status, text="upstream busy")

    calls = _mock_upstream(monkeypatch, tile_proxy, handler)
    resp = client.get("/api/v1/map/tiles/tianditu/3/6/3")

    assert resp.status_code == 200
    assert len(calls) == 3  # 首次 + 2 次换子域重试
    hosts = {c.url.host for c in calls}
    assert len(hosts) == 3  # 每次命中不同子域


def test_tile_network_error_maps_to_502(map_api, monkeypatch):
    client, install = map_api
    install([_entry("tianditu", browser_tk="tdt-key")])

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    calls = _mock_upstream(monkeypatch, tile_proxy, handler)
    resp = client.get("/api/v1/map/tiles/tianditu/3/6/3")

    assert resp.status_code == 502
    assert resp.json()["code"] == 2008
    assert len(calls) >= 3  # 网络类失败同样换子域重试


def test_tile_cache_hit_avoids_second_request(map_api, monkeypatch):
    client, install = map_api
    install([_entry("tianditu", browser_tk="tdt-key")])
    calls = _mock_upstream(
        monkeypatch, tile_proxy,
        lambda request: httpx.Response(200, content=b"PNG", headers={"content-type": "image/png"}),
    )
    assert client.get("/api/v1/map/tiles/tianditu/3/6/3").status_code == 200
    assert client.get("/api/v1/map/tiles/tianditu/3/6/3").status_code == 200
    assert len(calls) == 1  # 第二次命中内存缓存


def test_tile_amap_works_without_any_key(map_api, monkeypatch):
    client, install = map_api
    install([])  # 高德未配置任何 key
    calls = _mock_upstream(
        monkeypatch, tile_proxy,
        lambda request: httpx.Response(200, content=b"PNG", headers={"content-type": "image/png"}),
    )
    resp = client.get("/api/v1/map/tiles/amap/3/6/3")

    assert resp.status_code == 200
    assert "autonavi" in calls[0].url.host
    assert "tk" not in calls[0].url.params and "access_token" not in calls[0].url.params


def test_tianditu_label_tile_uses_cva_w_and_same_tk(map_api, monkeypatch):
    client, install = map_api
    install([_entry("tianditu", browser_tk="tdt-key")])
    calls = _mock_upstream(
        monkeypatch, tile_proxy,
        lambda request: httpx.Response(200, content=b"PNG", headers={"content-type": "image/png"}),
    )
    resp = client.get("/api/v1/map/tiles/tianditu-label/3/6/3")

    assert resp.status_code == 200
    assert calls[0].url.params.get("T") == "cva_w"
    assert calls[0].url.params.get("tk") == "tdt-key"  # 复用母 provider 的 tk


def test_tile_invalid_coords_rejected(map_api):
    client, _ = map_api
    resp = client.get("/api/v1/map/tiles/amap/99/0/0")
    assert resp.status_code == 422  # VALIDATION 统一映射 422
    assert resp.json()["code"] == 1001


# ---------------------------------------------------------------- 多凭据端点

def test_put_and_get_credentials_roundtrip(map_api):
    client, _ = map_api
    resp = client.put(
        "/api/v1/map/credentials",
        json={"provider_id": "amap",
              "fields": {"js_key": "js-1", "security_js_code": "sec-1", "service_key": "svc-1"}},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["fields"] == {
        "js_key": True, "security_js_code": True, "service_key": True,
    }

    # 落盘为加密 JSON，读回字段完整
    saved = cs.get_config_store().load()
    entry = saved["map"]["providers"][0]
    assert entry["key_enc"].startswith("ENC:")
    assert "svc-1" not in entry["key_enc"]
    creds = json.loads(decrypt(entry["key_enc"]))
    assert creds == {"js_key": "js-1", "security_js_code": "sec-1", "service_key": "svc-1"}

    # 脱敏视图：只回布尔
    view = client.get("/api/v1/map/credentials")
    assert view.status_code == 200
    body = view.json()["data"]
    assert body["providers"]["amap"]["fields"]["service_key"] is True
    assert "svc-1" not in json.dumps(body)


def test_put_credentials_rejects_unknown_field(map_api):
    client, _ = map_api
    resp = client.put(
        "/api/v1/map/credentials",
        json={"provider_id": "amap", "fields": {"nope": "x"}},
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == 1001


# ---------------------------------------------------------------- POI / 地理编码

def test_poi_search_uses_service_key_and_wgs84(map_api, monkeypatch):
    client, install = map_api
    install([_entry("amap", service_key="svc-1")])
    calls = _mock_upstream(
        monkeypatch, poi_adapter,
        lambda request: httpx.Response(200, json={
            "status": "1", "info": "OK",
            "pois": [{"id": "B001", "name": "星巴克", "address": "中关村大街1号",
                      "location": "116.404,39.915", "type": "餐饮服务"}],
        }),
    )
    resp = client.get("/api/v1/map/poi/search", params={"q": "咖啡", "provider": "amap"})

    assert resp.status_code == 200, resp.text
    pois = resp.json()["data"]
    assert calls[0].url.params.get("key") == "svc-1"  # 用的是 Web 服务 key
    assert pois[0]["id"].startswith("amap:")
    assert pois[0]["coord_system"] == "WGS84"
    assert pois[0]["source_coord_system"] == "GCJ02"
    assert abs(pois[0]["lng"] - 116.404) < 0.02  # GCJ02 → WGS84 有偏移但不漂移


def test_geocode_returns_wgs84_and_source_coords(map_api, monkeypatch):
    client, install = map_api
    install([_entry("amap", service_key="svc-1")])
    calls = _mock_upstream(
        monkeypatch, poi_adapter,
        lambda request: httpx.Response(200, json={
            "status": "1", "info": "OK",
            "geocodes": [{"formatted_address": "北京市海淀区中关村", "short_address": "中关村",
                          "location": "116.316,39.983"}],
        }),
    )
    resp = client.get("/api/v1/map/geocode", params={"address": "中关村", "provider": "amap"})

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert "/v3/geocode/geo" in str(calls[0].url)
    assert data["name"] and data["address"]
    assert data["location"]["coord_system"] == "WGS84"
    assert data["source_location"]["coord_system"] == "GCJ02"
    assert abs(data["source_location"]["lng"] - 116.316) < 1e-6
    assert abs(data["location"]["lng"] - data["source_location"]["lng"]) > 1e-4
    assert data["coord_system"] == "WGS84"


def test_geocode_without_service_key_returns_2009(map_api):
    client, install = map_api
    install([])
    resp = client.get("/api/v1/map/geocode", params={"address": "中关村"})
    assert resp.status_code == 400
    assert resp.json()["code"] == 2009


# ---------------------------------------------------------------- 路线规划

def test_route_driving_returns_wgs84_polyline(map_api, monkeypatch):
    client, install = map_api
    install([_entry("amap", service_key="svc-1")])
    calls = _mock_upstream(
        monkeypatch, route_service,
        lambda request: httpx.Response(200, json={
            "status": "1", "info": "OK",
            "route": {"paths": [{
                "distance": "12345", "duration": "1800",
                "steps": [
                    {"instruction": "沿中关村大街向南行驶", "distance": "1200", "duration": "300",
                     "polyline": "116.316,39.983;116.320,39.980"},
                    {"instruction": "右转进入北四环", "distance": "11145", "duration": "1500",
                     "polyline": "116.320,39.980;116.350,39.970"},
                ],
            }]},
        }),
    )
    resp = client.post("/api/v1/map/route", json={
        "origin": {"lng": 116.31, "lat": 39.98, "coord_system": "WGS84"},
        "destination": {"lng": 116.35, "lat": 39.97, "coord_system": "WGS84"},
        "waypoints": [{"lng": 116.33, "lat": 39.975}],
        "mode": "driving",
    })

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert "/v3/direction/driving" in str(calls[0].url)
    assert calls[0].url.params.get("waypoints")  # 途经点已带上（GCJ02）
    assert data["distance_m"] == 12345
    assert data["duration_s"] == 1800
    assert data["coord_system"] == "WGS84"
    assert len(data["polyline"]) >= 2
    assert len(data["steps"]) == 2
    assert data["steps"][0]["instruction"] == "沿中关村大街向南行驶"
    # 折线已从 GCJ02 转回 WGS84（与原始值有小幅偏移）
    assert abs(data["polyline"][0][0] - 116.316) < 0.02


def test_route_transit_extracts_railway_number(map_api, monkeypatch):
    client, install = map_api
    install([_entry("amap", service_key="svc-1")])
    _mock_upstream(
        monkeypatch, route_service,
        lambda request: httpx.Response(200, json={
            "status": "1", "info": "OK",
            "route": {"transits": [{
                "duration": "7200", "distance": "1200000",
                "segments": [
                    {"walk": {"distance": "500", "duration": "400", "instruction": "步行至地铁站"},
                     "bus": {"instruction": "乘坐地铁", "distance": "8000",
                             "buslines": [{"name": "地铁1号线", "duration": "1200",
                                           "departure_stop": {"name": "中关村站"},
                                           "arrival_stop": {"name": "北京南站"},
                                           "polyline": "116.316,39.983;116.320,39.900"}]}},
                    {"railway": {"name": "G101", "trip": "北京南-上海虹桥", "duration": "18000",
                                 "departure_stop": {"name": "北京南站"},
                                 "arrival_stop": {"name": "上海虹桥站"},
                                 "polyline": "116.320,39.900;121.320,31.190"}},
                ],
            }]},
        }),
    )
    resp = client.post("/api/v1/map/route", json={
        "origin": {"lng": 116.31, "lat": 39.98},
        "destination": {"lng": 121.32, "lat": 31.19},
        "mode": "transit",
        "city": "北京",
        "cityd": "上海",
    })

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    types = [seg["type"] for seg in data["segments"]]
    assert "bus" in types and "railway" in types
    railway = next(seg for seg in data["segments"] if seg["type"] == "railway")
    assert railway["name"] == "G101"  # 高铁班次
    assert data["duration_s"] == 7200


def test_route_without_key_returns_2009(map_api):
    client, install = map_api
    install([])
    resp = client.post("/api/v1/map/route", json={
        "origin": {"lng": 116.31, "lat": 39.98},
        "destination": {"lng": 116.35, "lat": 39.97},
        "mode": "driving",
    })
    assert resp.status_code == 400
    assert resp.json()["code"] == 2009


# ---------------------------------------------------------------- 导航深链

def test_navigation_links_compliant_apps_with_coord_conversion(map_api):
    client, _ = map_api
    resp = client.post("/api/v1/map/navigation-links", json={
        "name": "天安门", "lng": 116.397428, "lat": 39.90923, "coord_system": "WGS84",
    })
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]

    assert set(data["links"]) == {"amap", "baidu", "tencent"}
    assert data["links"]["amap"]["coordSystem"] == "GCJ02"
    assert data["links"]["baidu"]["coordSystem"] == "BD09"
    assert "coordinate=gaode" in data["links"]["amap"]["url"]
    assert "coord_type=bd09ll" in data["links"]["baidu"]["url"]
    assert quote("天安门") in data["links"]["amap"]["url"]

    w = data["resolved"]["WGS84"]
    g = data["resolved"]["GCJ02"]
    b = data["resolved"]["BD09"]
    assert abs(w["lng"] - 116.397428) < 1e-6
    assert abs(g["lng"] - w["lng"]) > 1e-4   # GCJ02 与 WGS84 存在偏移
    assert abs(b["lng"] - g["lng"]) > 1e-4   # BD09 相对 GCJ02 再次偏移


# ---------------------------------------------------------------- 百度删除回归

def test_baidu_tile_is_unknown_provider(map_api):
    client, _ = map_api
    resp = client.get("/api/v1/map/tiles/baidu/3/6/3")
    assert resp.status_code == 502
    assert resp.json()["code"] == 2006


def test_baidu_poi_provider_rejected(map_api):
    client, _ = map_api
    resp = client.get("/api/v1/map/poi/search", params={"q": "咖啡", "provider": "baidu"})
    assert resp.status_code == 502
    body = resp.json()
    assert body["code"] == 2006
    assert "不支持" in body["message"]
