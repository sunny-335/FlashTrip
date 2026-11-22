"""地图配置契约：预设元数据自动带出、合规文案删除、设置页免解锁保存。

本文件不发起任何真实网络请求；PUT /settings 用例通过依赖覆盖注入登录用户与
独立内存 DB，只验证配置合并与脱敏，不触碰外部服务。
"""
from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1 import deps
from app.core import config_store as cs
from app.core.config_store import ConfigStore, get_config_store
from app.core.errors import ErrorCode
from app.core.security import decrypt, encrypt
from app.db.base import Base
from app.models.config import AiProviderConfig, MapProviderConfig, UserPreferences
from app.services import install_service as svc
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
    # 国内三家审图号由服务商公示，预置为空，绝不编造具体编号
    for pid in ("amap", "baidu", "tianditu"):
        assert next(p for p in providers if p["id"] == pid)["auditNumber"] == ""


def test_attributions_match_public_credits():
    """署名逐家与公开口径一致，不擅自增删。"""
    credits = {
        "openfreemap-liberty": "© OpenFreeMap · © OpenStreetMap contributors",
        "mapbox": "© Mapbox · © OpenStreetMap contributors",
        "amap": "© 高德地图",
        "baidu": "© 百度地图",
        "tianditu": "© 天地图",
    }
    by_id = {p["id"]: p for p in reg.list_providers(cfg={"map": {}})}
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
    """向导/设置里残留的手填技术字段一律不得覆盖预设（防空白地图）。"""
    cfg = {
        "map": {
            "providers": {
                "openfreemap-liberty": {
                    "style_url": "https://evil.example/raster.json",
                    "styleUrl": "https://evil.example/raster.json",
                    "tile_url_template": "https://evil.example/{z}/{x}/{y}.png",
                    "tileUrlTemplate": "https://evil.example/{z}/{x}/{y}.png",
                    "coord_system": "GCJ02",
                    "coordSystem": "GCJ02",
                    "attribution": "伪造署名",
                    "audit_number": "GS(2025)0000号",
                    "auditNumber": "GS(2025)0000号",
                    "needs_token": True,
                    "needsToken": True,
                    "label": "被篡改的名称",
                    "enabled": False,
                    "default_style": "dark",
                    "key_enc": "ENC:placeholder",
                }
            }
        }
    }
    defn = next(d for d in reg._merged_definitions(cfg) if d["id"] == "openfreemap-liberty")
    # 元数据全部以预设为准
    assert defn["styleUrl"] == "https://tiles.openfreemap.org/styles/liberty"
    assert defn["tileUrlTemplate"] is None  # 永远走矢量 style，不降级成 raster 代理
    assert defn["coordSystem"] == "WGS84"
    assert defn["attribution"] == "© OpenFreeMap · © OpenStreetMap contributors"
    assert defn["auditNumber"] == ""
    assert defn["needsToken"] is False
    assert defn["label"] == "OpenFreeMap · Liberty"
    # 仅运行态（密钥状态 / enabled / default_style）允许合并
    assert defn["hasKey"] is True
    assert defn["enabled"] is False
    assert defn["defaultStyle"] == "dark"
    # 有 styleUrl 且无 tileUrlTemplate 时返回引用式 style
    style = reg._public_style(defn)
    assert style["version"] == 8
    assert style["styleUrl"] == defn["styleUrl"]
    assert style["sources"] == {} and style["layers"] == []
    assert style["coordSystem"] == "WGS84"


def test_map_config_has_no_compliance_note_and_defaults_to_liberty():
    cfg = reg.map_config(cfg={"map": {}})
    assert set(cfg) == {"auditNumber", "defaultProviderId", "providers"}
    assert cfg["defaultProviderId"] == "openfreemap-liberty"
    # 用户显式配置且已启用时优先
    cfg2 = reg.map_config(cfg={"map": {"default_provider_id": "openfreemap-dark"}})
    assert cfg2["defaultProviderId"] == "openfreemap-dark"


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
