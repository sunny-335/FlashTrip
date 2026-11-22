"""安装向导契约：status 公开、未安装守卫 2001、锁定后 install 2002。"""
from __future__ import annotations

from app.core.config_store import ConfigStore
from app.core.errors import ErrorCode


def test_wizard_status_is_public(client, monkeypatch):
    # 模拟「未安装」：公开前缀仍可访问，安装守卫不得拦截
    monkeypatch.setattr(ConfigStore, "is_installed", lambda self: False)

    resp = client.get("/api/v1/wizard/status")

    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == ErrorCode.OK
    assert body["data"]["installed"] is False
    assert body["data"]["version"]
    assert len(body["data"]["steps"]) == 6


def test_not_installed_guard_returns_2001(client, monkeypatch):
    monkeypatch.setattr(ConfigStore, "is_installed", lambda self: False)

    resp = client.get("/api/v1/trips")

    assert resp.status_code == 503
    assert resp.json()["code"] == ErrorCode.INSTALL_REQUIRED
    assert resp.headers["content-type"].startswith("application/json")


def test_locked_install_returns_2002(client, monkeypatch):
    # 已安装且未解锁（config.json 无 unlocked_at）→ INSTALL_LOCKED
    monkeypatch.setattr(ConfigStore, "is_installed", lambda self: True)

    resp = client.post(
        "/api/v1/wizard/install",
        json={"admin": {"username": "owner", "password": "password123"}},
    )

    assert resp.status_code == 409
    assert resp.json()["code"] == ErrorCode.INSTALL_LOCKED


def test_wizard_config_is_redacted(client):
    resp = client.get("/api/v1/wizard/config")

    assert resp.status_code == 200
    cfg = resp.json()["data"]
    # 主密钥/密文绝不出后端（未安装时该字段可能不存在，同样视为安全）
    assert cfg.get("secret_key") in (None, "***")
    for provider in (cfg.get("ai") or {}).get("providers", []):
        assert "api_key_enc" not in provider
    for provider in (cfg.get("map") or {}).get("providers", []):
        assert "key_enc" not in provider
