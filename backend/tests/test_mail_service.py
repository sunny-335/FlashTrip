"""邮件服务契约：模板渲染、Markdown 结构化、测试收件人、配置加密、每日提醒去重。

不发任何真实邮件；SMTP 一律 monkeypatch 为立即失败或纯记录。
"""
from __future__ import annotations

import re
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import config_store as cs
from app.core.config_store import ConfigStore
from app.core.security import decrypt
from app.db.base import Base
from app.models.mail import MailLog
from app.services import mail_service as ms


@pytest.fixture()
def mail_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine, tables=[MailLog.__table__])
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    yield session
    session.close()
    engine.dispose()


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


def test_markdown_to_html_structures_and_escapes():
    html = ms.markdown_to_html("## 今日天气\n- **加粗** 要点\n- 第二条\n\n普通段落")
    assert "<h3" in html and "今日天气" in html
    assert "<ul" in html and html.count("<li") == 2
    assert "<strong>加粗</strong>" in html
    assert "<p" in html and "普通段落" in html
    # 转义：任何输入中的脚本标签都不会原样出现
    evil = ms.markdown_to_html("<script>alert(1)</script> **安全**")
    assert "<script>" not in evil and "&lt;script&gt;" in evil
    assert "<strong>安全</strong>" in evil


def test_build_advice_email_is_structured_not_escaped_markdown():
    weather = {
        "current": {"weather": "晴", "temperature": 26.0, "humidity": 60,
                    "wind": "东南 3", "alerts": ["大风预警"]},
        "forecast": [{"date": "2026-11-23", "week": "周一", "weather_day": "晴",
                      "weather_night": "多云", "temp_min": 18.0, "temp_max": 28.0, "pop": 0.2}],
        "advice_hints": ["注意防晒"],
    }
    subject, html = ms.build_advice_email(
        {"title": "苏州三日游", "destination": "苏州", "start_date": "2026-11-23"}, "## 出行建议\n- 带伞", weather,
    )
    assert "苏州三日游" in subject
    assert "天气概况" in html and "逐日天气" in html and "出行建议" in html
    assert "<ul" in html and "<li" in html               # 逐日/建议列表已渲染为 HTML
    assert "<strong>" in html                              # Markdown 加粗生效
    assert "{{advice}}" not in html and "## 出行建议" not in html  # 不再显示 Markdown 原文
    assert "晴" in html and "苏州" in html


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


def _enabled_cfg(**over) -> dict:
    cfg = {
        "enabled": True, "host": "127.0.0.1", "port": 1, "user": "bot",
        "password_enc": "", "from_addr": "bot@example.com",
        "from_name": "瞬旅 FlashTrip", "use_ssl": True, "use_tls": False,
        "timeout_s": 1, "default_recipients": [], "test_recipients": [],
    }
    cfg.update(over)
    return cfg


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


def test_test_mail_sends_to_recipients_not_sender(monkeypatch):
    """测试邮件发给配置的收件人列表，绝不发给发件人自己。"""
    captured: dict = {}

    def fake_send(cfg, recipients, msg, *, password=None):
        captured["recipients"] = list(recipients)

    monkeypatch.setattr(ms, "_raw_mail_config", lambda: _enabled_cfg(
        default_recipients=["a@example.com", "b@example.com"],
    ))
    monkeypatch.setattr(ms, "_smtp_send", fake_send)

    result = ms.test_mail()
    assert result["ok"] is True
    assert captured["recipients"] == ["a@example.com", "b@example.com"]
    assert "bot@example.com" not in captured["recipients"]


def test_test_mail_prefers_test_recipients(monkeypatch):
    captured: dict = {}

    def fake_send(cfg, recipients, msg, *, password=None):
        captured["recipients"] = list(recipients)

    monkeypatch.setattr(ms, "_raw_mail_config", lambda: _enabled_cfg(
        default_recipients=["default@example.com"],
        test_recipients=["test@example.com"],
    ))
    monkeypatch.setattr(ms, "_smtp_send", fake_send)

    assert ms.test_mail()["ok"] is True
    assert captured["recipients"] == ["test@example.com"]


def test_test_mail_without_recipients_reports_error(monkeypatch):
    monkeypatch.setattr(ms, "_raw_mail_config", lambda: _enabled_cfg(
        default_recipients=[], test_recipients=[],
    ))
    monkeypatch.setattr(ms, "_smtp_send", lambda *a, **k: pytest.fail("无收件人不应发送"))
    result = ms.test_mail()
    assert result["ok"] is False
    assert "收件人" in result["message"]


def test_daily_reminder_dedup_by_trip_and_date(mail_db):
    day = datetime(2026, 11, 23).date().isoformat()
    mail_db.add(MailLog(
        to_addr="a@example.com", subject=f"【今日出行】{day} · 苏州三日游 · 天气与建议",
        template=ms.DAILY_TEMPLATE, status="sent", trip_id="trip-1",
    ))
    mail_db.commit()

    assert ms.daily_reminder_sent(mail_db, "trip-1", day) is True
    assert ms.daily_reminder_sent(mail_db, "trip-1", "2026-11-24") is False
    assert ms.daily_reminder_sent(mail_db, "trip-2", day) is False
