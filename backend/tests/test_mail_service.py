"""邮件服务契约：模板渲染、配置加密脱敏、SMTP 不可达时安全失败。

不发任何真实邮件；SMTP 一律 monkeypatch 为立即失败。
"""
from __future__ import annotations

import re

import pytest

from app.core import config_store as cs
from app.core.config_store import ConfigStore
from app.core.security import decrypt
from app.services import mail_service as ms


@pytest.mark.parametrize("name", ms.TEMPLATE_NAMES)
def test_render_template_nonempty_and_chinese(name):
    html = ms.render_template(name, {
        "trip_title": "苏州三日游", "destination": "苏州", "advice": "记得带伞",
        "title": "通知", "content": "内容",
    })
    assert html.strip()
    assert "<html" in html.lower()
    assert re.search(r"[\u4e00-\u9fff]", html)


def test_render_template_missing_context_is_safe():
    html = ms.render_template("generic", {})
    assert re.search(r"[\u4e00-\u9fff]", html)
    assert "{{" not in html  # 所有占位都被默认值替换，不抛异常


def test_render_template_unknown_name_falls_back():
    assert "<html" in ms.render_template("not_exist", {"title": "你好"}).lower()


def test_template_names_and_meta():
    assert len(ms.TEMPLATE_NAMES) == 5
    meta = ms.list_templates()
    assert {item["name"] for item in meta} == set(ms.TEMPLATE_NAMES)
    assert all(item["label"] and item["description"] for item in meta)


def test_save_config_encrypts_and_redacts(monkeypatch, tmp_path):
    store = ConfigStore(path=tmp_path / "config.json")
    store.save({"installed": True})
    monkeypatch.setattr(cs, "_store", store)

    out = ms.save_mail_config({
        "host": "smtp.example.com", "user": "bot",
        "password": "s3cr3t", "enabled": True,
    })
    assert out["has_password"] is True
    assert "password_enc" not in out and "password" not in out
    saved = store.load()["mail"]
    assert "s3cr3t" not in str(saved)
    assert decrypt(saved["password_enc"]) == "s3cr3t"

    # 留空 password 时保留旧密文，不误清密钥
    ms.save_mail_config({"host": "smtp2.example.com"})
    assert decrypt(store.load()["mail"]["password_enc"]) == "s3cr3t"


def _enabled_cfg() -> dict:
    return {
        "enabled": True, "host": "127.0.0.1", "port": 1, "user": "bot",
        "password_enc": "", "from_addr": "bot@example.com",
        "from_name": "瞬旅 FlashTrip", "use_ssl": True, "use_tls": False,
        "timeout_s": 1, "default_recipients": [],
    }


def test_send_mail_unreachable_returns_false(monkeypatch):
    def _boom(*args, **kwargs):
        raise OSError("smtp unreachable")

    monkeypatch.setattr(ms, "_raw_mail_config", _enabled_cfg)
    monkeypatch.setattr(ms, "_write_log", lambda *args, **kwargs: None)
    monkeypatch.setattr(ms.smtplib, "SMTP_SSL", _boom)
    result = ms.send_mail("someone@example.com", "主题", "<p>内容</p>")
    assert result["ok"] is False
    assert isinstance(result["error"], str) and result["error"]


def test_send_mail_disabled_never_throws(monkeypatch):
    monkeypatch.setattr(ms, "_raw_mail_config", lambda: {"enabled": False})
    monkeypatch.setattr(ms, "_write_log", lambda *args, **kwargs: None)
    assert ms.send_mail("a@b.com", "主题", "<p>x</p>")["ok"] is False


def test_test_mail_never_throws(monkeypatch):
    monkeypatch.setattr(ms, "_raw_mail_config", lambda: {"host": "", "enabled": False})
    result = ms.test_mail()
    assert result["ok"] is False and "message" in result
