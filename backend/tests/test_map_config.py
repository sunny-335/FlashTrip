"""地图配置契约：预设元数据自动带出、合规文案删除、设置页免解锁保存。

本文件不发起任何真实网络请求；PUT /settings 用例通过依赖覆盖注入登录用户与
独立内存 DB，只验证配置合并与脱敏，不触碰外部服务。
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1 import deps
from app.core import config_store as cs
from app.core.config_store import ConfigStore, get_config_store
from app.core.errors import AppError, ErrorCode
from app.core.security import decrypt, encrypt
from app.db.base import Base
from app.models.config import AiProviderConfig, MapProviderConfig, UserPreferences
from app.services import install_service as svc
from app.services.map import credentials as cred
from app.services.map import provider_registry as reg


# ---------------------------------------------------------------- 预设元数据

def test_list_providers_redacts_and_drops_compliance_note():
    """每个供应商都有非空署名、complianceNote 恒空、审图号来自预设。"""
    providers = reg.list_providers(cfg={"map": {}})
    assert providers  # 预设供应商列表非空
    presets = {d["id"]: d for d in reg.PROVIDER_DEFS}
    for p in providers:
        assert p["attribution"].strip()
        assert p["complianceNote"] == ""
        assert p["auditNumber"] == presets[p["id"]]["auditNumber"]
        # 需要密钥的供应商不下发 styleUrl，避免前端直连却拿不到 key
        if p["needsToken"]:
            assert p["styleUrl"] is None
    # 国内两家审图号由服务商公示，预置为空，绝不编造具体编号
    for pid in ("amap", "tianditu"):
        assert next(p for p in providers if p["id"] == pid)["auditNumber"] == ""


def test_attributions_match_public_credits():
    """已启用的合规供应商署名逐家与预设一致。"""
    credits = {
        "amap": "© 高德地图",
        "tianditu": "© 天地图",
    }
    by_id = {p["id"]: p for p in reg.list_providers(cfg={"map": {}})}
    assert set(by_id) == {"amap", "tianditu"}
    for pid, credit in credits.items():
        assert by_id[pid]["attribution"] == credit


def test_explicit_audit_number_takes_priority():
    """用户在 config 里显式填过 audit_number 时优先，否则回落到预设。

    这里的值仅用于验证优先级，是一个中性占位符，并非真实审图号。
    """
    cfg = {"map": {"providers": {"amap": {"audit_number": "USER_OVERRIDE"}}}}
    amap = next(p for p in reg.list_providers(cfg) if p["id"] == "amap")
    assert amap["auditNumber"] == "USER_OVERRIDE"


def test_merged_definitions_never_overrides_preset_metadata():
    """设置中的残留技术字段不能覆盖高德预设元数据。"""
    cfg = {
        "map": {
            "providers": {
                "amap": {
                    "style_url": "https://evil.example/raster.json",
                    "tile_url_template": "https://evil.example/{z}/{x}/{y}.png",
                    "coord_system": "WGS84",
                    "attribution": "伪造署名",
                    "label": "被篡改的名称",
                    "enabled": True,
                    "key_enc": "ENC:placeholder",
                }
            }
        }
    }
    defn = next(d for d in reg._merged_definitions(cfg) if d["id"] == "amap")
    assert defn["tileUrlTemplate"].startswith("https://webrd")
    assert defn["coordSystem"] == "GCJ02"
    assert defn["attribution"] == "© 高德地图"
    assert defn["label"] == "高德地图"
    assert defn["hasKey"] is True


def test_map_config_has_no_compliance_note_and_defaults_to_amap():
    cfg = reg.map_config(cfg={"map": {}})
    assert set(cfg) == {"auditNumber", "defaultProviderId", "providers"}
    assert cfg["defaultProviderId"] == "amap"
    cfg2 = reg.map_config(cfg={"map": {"default_provider_id": "tianditu"}})
    # 天地图未配置 tk 时不可用，默认值安全回退到可用的高德底图
    assert cfg2["defaultProviderId"] == "amap"


def test_read_config_sanitized_handles_dict_and_none_providers(monkeypatch, tmp_path):
    """map.providers 为 dict / None / 空列表时都不抛异常，且密钥只回布尔标记。"""
    for raw in ({"amap": {"key_enc": "ENC:x", "enabled": True}}, None, []):
        store = ConfigStore(path=tmp_path / "config.json")
        store.save({"installed": True, "map": {"providers": raw}})
        monkeypatch.setattr(cs, "_store", store)
        out = svc.read_config_sanitized()
        providers = out["map"]["providers"]
        assert isinstance(providers, list)
        for p in providers:
            assert "key_enc" not in p and "key" not in p
            assert "has_key" in p


# ---------------------------------------------------------------- 设置页保存

def test_put_settings_saves_without_unlock_and_keeps_other_providers(
    client, monkeypatch, tmp_path
):
    """未解锁也能 PUT /settings 保存地图配置，且未提交的供应商不丢失。"""
    # ① 隔离配置：预置两个供应商，且不含 unlocked_at（默认未解锁）
    store = ConfigStore(path=tmp_path / "config.json")
    store.save(
        {
            "installed": True,
            "secret_key": "unit-test-secret",
            "database": {"url": "sqlite://", "dialect": "sqlite"},
            "redis": {"url": "", "enabled": False},
            "ai": {"providers": []},
            "map": {
                "providers": [
                    {"id": "amap", "key_enc": encrypt("old-amap-key"), "enabled": True},
                    {"id": "tianditu", "key_enc": encrypt("old-tdt-key"), "enabled": True},
                ],
                "default_provider_id": "amap",
                "audit_number": "",
            },
            "security": {"ai_tools_enabled": False},
        }
    )
    monkeypatch.setattr(cs, "_store", store)
    assert not store.is_unlocked()  # 关键前提：处于未解锁状态

    # ② 独立内存 DB，只建 update_config 会触碰的三张表
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            AiProviderConfig.__table__,
            MapProviderConfig.__table__,
            UserPreferences.__table__,
        ],
    )
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = Session()

    fake_user = SimpleNamespace(id="u-1", role="owner", must_set_password=False)
    monkeypatch.setitem(client.app.dependency_overrides, deps.require_user, lambda: fake_user)
    monkeypatch.setitem(client.app.dependency_overrides, deps.get_db, lambda: db)

    try:
        # ③ 只提交一个供应商的 key / enabled
        resp = client.put(
            "/api/v1/settings",
            json={"map_providers": [{"id": "amap", "key": "new-amap-key", "enabled": False}]},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["code"] == ErrorCode.OK

        # ④ 保存结果：提交项更新，未提交项原样保留
        saved = get_config_store().load()
        providers = {p["id"]: p for p in saved["map"]["providers"]}
        assert "tianditu" in providers  # 未提交的供应商没有丢失
        assert decrypt(providers["tianditu"]["key_enc"]) == "old-tdt-key"
        assert providers["tianditu"]["enabled"] is True
        assert decrypt(providers["amap"]["key_enc"]) == "new-amap-key"
        assert providers["amap"]["enabled"] is False
        assert "unlocked_at" not in saved  # 全程未解锁也能保存成功

        # ⑤ 响应脱敏：密钥只回 has_key，绝不回明文或密文
        returned = {p["id"]: p for p in body["data"]["map"]["providers"]}
        assert "key_enc" not in returned["amap"] and "key" not in returned["amap"]
        assert returned["amap"]["has_key"] is True

        # ⑥ DB 镜像的技术元数据来自预设，而非前端手填
        amap_row = (
            db.query(MapProviderConfig)
            .filter(MapProviderConfig.provider_id == "amap")
            .first()
        )
        assert amap_row is not None
        assert amap_row.coord_system == "GCJ02"
        assert amap_row.attribution == "© 高德地图"
        assert amap_row.audit_number == ""
    finally:
        db.close()
        engine.dispose()


# ---------------------------------------------------------------- 能力拆分 / 多凭据

def test_baidu_provider_removed():
    """百度 Provider 彻底删除：预设与能力表均无 baidu，取定义直接报错。"""
    assert "baidu" not in {d["id"] for d in reg.PROVIDER_DEFS}
    assert "baidu" not in reg.POI_PROVIDERS
    with pytest.raises(AppError):
        reg.get_provider_def({"map": {}}, "baidu")


def test_needs_token_split_amap_tiles_without_key():
    """高德瓦片无需 key：未填任何 key 仍 enabled 且 tilesReady，服务能力单列。"""
    cfg = {"map": {}}
    amap = next(p for p in reg.list_providers(cfg) if p["id"] == "amap")
    assert amap["needsTileKey"] is False
    assert amap["needsServiceKey"] is True
    assert amap["enabled"] is True
    assert amap["tilesReady"] is True
    assert amap["poiReady"] is False
    assert amap["routeReady"] is False
    assert amap["servicesReady"] is False

    # 配置 Web 服务 key 后 POI / 路线就绪
    cfg2 = {"map": {"providers": [
        {"id": "amap", "key_enc": encrypt(json.dumps({"service_key": "svc"}))}
    ]}}
    amap2 = next(p for p in reg.list_providers(cfg2) if p["id"] == "amap")
    assert amap2["poiReady"] is True
    assert amap2["routeReady"] is True
    assert amap2["servicesReady"] is True


def test_tianditu_needs_tile_key_and_label_layer():
    """天地图瓦片需 tk；公开 style 双 source 叠加 cva_w 注记层，internal 不出列。"""
    cfg = {"map": {}}
    tdt = next(p for p in reg.list_providers(cfg) if p["id"] == "tianditu")
    assert tdt["needsTileKey"] is True
    assert tdt["needsServiceKey"] is True
    assert tdt["enabled"] is False  # 未配 tk 时瓦片不可用
    assert tdt["tilesReady"] is False
    assert tdt["labelLayer"]["providerId"] == "tianditu-label"
    assert "/map/tiles/tianditu-label/" in tdt["labelLayer"]["tiles"][0]

    # internal 注记层不出现在公开供应商列表
    assert "tianditu-label" not in {p["id"] for p in reg.list_providers(cfg)}

    # 公开 style 双 source，且不含任何密钥占位值
    sources = tdt["style"]["sources"]
    assert "raster-tianditu" in sources
    assert "raster-tianditu-label" in sources
    assert "{key}" not in json.dumps(tdt["style"])


def test_legacy_single_key_migrates_to_expected_field():
    """旧单 key 迁移：amap→service_key、tianditu→browser_tk；服务 key 允许回退。"""
    amap_cfg = {"map": {"providers": {"amap": {"key_enc": encrypt("old-amap-key")}}}}
    assert cred.get_provider_credentials(amap_cfg, "amap") == {"service_key": "old-amap-key"}

    tdt_cfg = {"map": {"providers": {"tianditu": {"key_enc": encrypt("old-tdt-tk")}}}}
    assert cred.get_provider_credentials(tdt_cfg, "tianditu") == {"browser_tk": "old-tdt-tk"}
    # 天地图 tk 常两用：服务 key 缺失时回退 browser_tk
    assert cred.resolve_service_key(tdt_cfg, "tianditu") == "old-tdt-tk"

    # 高德 JS key 实测不能调 Web 服务，绝不回退成服务 key
    js_only = {"map": {"providers": {
        "amap": {"key_enc": encrypt(json.dumps({"js_key": "js"}))}
    }}}
    assert cred.resolve_service_key(js_only, "amap") == ""


def test_structured_credentials_roundtrip_and_redaction(tmp_path):
    """多凭据落盘为加密 JSON；读回正确；脱敏视图与密文均不含明文。"""
    store = ConfigStore(path=tmp_path / "config.json")
    store.save({"installed": True, "secret_key": "unit-test-secret", "map": {"providers": []}})

    result = cred.save_provider_credentials(
        store, "amap",
        {"js_key": " js-1 ", "security_js_code": "sec-1", "service_key": "svc-1"},
    )
    assert result["fields"] == {"js_key": True, "security_js_code": True, "service_key": True}

    saved = store.load()
    entry = saved["map"]["providers"][0]
    assert entry["id"] == "amap"
    assert entry["key_enc"].startswith("ENC:")
    assert "svc-1" not in entry["key_enc"]  # 落盘只有密文
    assert cred.get_provider_credentials(saved, "amap") == {
        "js_key": "js-1", "security_js_code": "sec-1", "service_key": "svc-1",
    }

    overview = cred.credential_overview(saved)
    assert overview["providers"]["amap"]["fields"]["service_key"] is True
    assert "svc-1" not in json.dumps(overview)

    # 空字符串 = 显式清除单字段，其余保留
    cred.save_provider_credentials(store, "amap", {"js_key": ""})
    remaining = cred.get_provider_credentials(store.load(), "amap")
    assert "js_key" not in remaining
    assert remaining["service_key"] == "svc-1"
