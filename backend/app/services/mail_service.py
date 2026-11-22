"""邮件服务：config.json 的 mail 段 + 标准库 smtplib/email，零新依赖。

安全约定：
- SMTP 口令经 encrypt() 后存 password_enc，仅在连接瞬间 decrypt() 使用；
  配置读取一律脱敏为 has_password 布尔，密文/明文绝不出后端、绝不写日志。
- 发送失败只记录异常类型名（SMTP 异常消息可能回显账号/口令）。
- send_mail 对调用方契约：绝不抛异常，失败返回 {"ok": False, "error": str}。
"""
from __future__ import annotations

import html as html_lib
import re
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr, formatdate
from typing import Any

from app.core.config_store import get_config_store
from app.core.logging import get_logger
from app.core.security import decrypt, encrypt
from app.models.mail import MailLog

log = get_logger(__name__)

_MAIL_DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "host": "",
    "port": 465,
    "user": "",
    "password_enc": "",
    "from_addr": "",
    "from_name": "瞬旅 FlashTrip",
    "use_ssl": True,
    "use_tls": False,
    "timeout_s": 10,
    "default_recipients": [],
}

TEMPLATE_NAMES = ("trip_weather_advice", "invite", "share", "test", "generic")

TEMPLATE_META = (
    ("trip_weather_advice", "行程天气出行建议", "临近出发时汇总天气、穿衣与装备建议"),
    ("invite", "协作邀请", "邀请成员加入行程并附一次性邀请链接"),
    ("share", "行程分享", "把公开分享链接发给同伴"),
    ("test", "测试邮件", "验证 SMTP 连通性与发件人配置"),
    ("generic", "通用通知", "系统通知的默认模板"),
)

# 模板变量缺省值：任何 {{变量名}} 缺失都不抛异常，且给出可读中文
_DEFAULT_CONTEXT: dict[str, str] = {
    "trip_title": "我的行程",
    "destination": "目的地",
    "start_date": "近期",
    "end_date": "待定",
    "weather_summary": "暂无实时天气数据",
    "advice": "出行前请关注天气变化，备好随身物品。",
    "inviter": "行程管理员",
    "invite_url": "",
    "share_url": "",
    "sender": "同行伙伴",
    "expire_hint": "链接可能设有有效期，请及时查看",
    "app_name": "瞬旅 FlashTrip",
    "time": "刚刚",
    "title": "通知",
    "content": "你有一条新的消息。",
}

_VAR_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


def _shell(title: str, body: str) -> str:
    """内联 CSS 的响应式卡片外壳，无外部图片/字体依赖。"""
    return (
        "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<title>" + html_lib.escape(title) + "</title></head>"
        "<body style=\"margin:0;padding:24px;background:#f3f6fb;color:#1f2937;"
        "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;\">"
        "<div style=\"max-width:600px;margin:0 auto;background:#ffffff;border-radius:16px;"
        "box-shadow:0 6px 24px rgba(15,23,42,.08);overflow:hidden;\">"
        "<div style=\"background:linear-gradient(135deg,#2563eb,#7c3aed);padding:22px 28px;color:#fff;\">"
        "<div style=\"font-size:20px;font-weight:700;\">瞬旅 FlashTrip</div>"
        "<div style=\"font-size:13px;opacity:.85;margin-top:4px;\">让每一次出发都从容</div></div>"
        "<div style=\"padding:28px;\"><h1 style=\"font-size:20px;margin:0 0 16px;\">"
        + html_lib.escape(title)
        + "</h1>" + body + "</div>"
        "<div style=\"padding:16px 28px;background:#f9fafb;color:#6b7280;font-size:12px;\">"
        "本邮件由瞬旅 FlashTrip 自动发送，请勿直接回复。</div></div></body></html>"
    )


_ADVICE_BODY = (
    "<p style=\"margin:0 0 16px;line-height:1.7;\">你好，旅程 <strong>{{trip_title}}</strong> "
    "将于 {{start_date}} 出发，目的地 {{destination}}，请留意以下天气与出行建议。</p>"
    "<div style=\"margin:0 0 18px;padding:14px 16px;background:#eff6ff;border-radius:10px;"
    "font-size:14px;line-height:1.7;\"><strong>当前天气</strong><br>{{weather_summary}}</div>"
    "<div style=\"padding:16px;background:#f9fafb;border-radius:10px;white-space:pre-wrap;"
    "line-height:1.8;font-size:14px;\">{{advice}}</div>"
    "<p style=\"margin:18px 0 0;color:#6b7280;font-size:13px;line-height:1.7;\">"
    "祝旅途顺利，记得根据天气增减衣物、备好雨具与随身药品。</p>"
)

_INVITE_BODY = (
    "<p style=\"margin:0 0 16px;line-height:1.7;\">{{inviter}} 邀请你一起参与行程 "
    "<strong>{{trip_title}}</strong>，共同规划交通、住宿与每日安排。</p>"
    "<div style=\"margin:18px 0;padding:14px 16px;background:#eff6ff;border-radius:10px;"
    "font-size:14px;word-break:break-all;line-height:1.7;\">邀请链接：{{invite_url}}</div>"
    "<p style=\"margin:0;color:#6b7280;font-size:13px;line-height:1.7;\">{{expire_hint}}。"
    "若非本人预期，请忽略本邮件。</p>"
)

_SHARE_BODY = (
    "<p style=\"margin:0 0 16px;line-height:1.7;\">{{sender}} 与你分享了行程 "
    "<strong>{{trip_title}}</strong>。</p>"
    "<div style=\"margin:18px 0;padding:14px 16px;background:#eff6ff;border-radius:10px;"
    "font-size:14px;word-break:break-all;line-height:1.7;\">分享链接：{{share_url}}</div>"
    "<p style=\"margin:0;color:#6b7280;font-size:13px;line-height:1.7;\">{{expire_hint}}，"
    "页面仅展示已公开的行程内容。</p>"
)

_TEST_BODY = (
    "<p style=\"margin:0 0 16px;line-height:1.7;\">这是一封来自 {{app_name}} 的测试邮件，"
    "用于确认 SMTP 发件配置是否正确。</p>"
    "<div style=\"padding:14px 16px;background:#ecfdf5;border-radius:10px;font-size:14px;"
    "line-height:1.7;\">收到本邮件即表示发信通道可用。发送时间：{{time}}。</p>"
)

_GENERIC_BODY = (
    "<p style=\"margin:0 0 16px;line-height:1.7;\">{{title}}</p>"
    "<div style=\"padding:14px 16px;background:#f9fafb;border-radius:10px;white-space:pre-wrap;"
    "font-size:14px;line-height:1.8;\">{{content}}</div>"
)

_TEMPLATES = {
    "trip_weather_advice": _shell("出行天气提醒：{{trip_title}}", _ADVICE_BODY),
    "invite": _shell("行程协作邀请", _INVITE_BODY),
    "share": _shell("行程分享：{{trip_title}}", _SHARE_BODY),
    "test": _shell("测试邮件", _TEST_BODY),
    "generic": _shell("{{title}}", _GENERIC_BODY),
}


def render_template(name: str, context: dict) -> str:
    """渲染 {{变量名}} 占位；变量缺失用中文默认值，绝不抛异常。"""
    body = _TEMPLATES.get(name) or _TEMPLATES["generic"]
    ctx = {key: value for key, value in (context or {}).items() if value is not None}

    def _replace(match: re.Match) -> str:
        key = match.group(1)
        value = ctx.get(key, _DEFAULT_CONTEXT.get(key, ""))
        return html_lib.escape(str(value), quote=True)

    return _VAR_RE.sub(_replace, body)


def list_templates() -> list[dict]:
    """模板名称 + 中文说明，供设置页展示。"""
    return [{"name": n, "label": label, "description": desc} for n, label, desc in TEMPLATE_META]


# ---------------------------------------------------------------- 配置读写

def _raw_mail_config() -> dict:
    """读取含密文的内部配置（仅服务端使用，绝不下发前端）。"""
    section = get_config_store().load().get("mail")
    merged: dict[str, Any] = dict(_MAIL_DEFAULTS)
    merged["default_recipients"] = list(_MAIL_DEFAULTS["default_recipients"])
    if isinstance(section, dict):
        for key, value in section.items():
            if key in _MAIL_DEFAULTS:
                merged[key] = value
    return merged


def _sanitized(section: dict) -> dict:
    """脱敏：password_enc 替换为 has_password 布尔。"""
    out = {key: value for key, value in section.items() if key != "password_enc"}
    out["has_password"] = bool(section.get("password_enc"))
    return out


def get_mail_config() -> dict:
    """脱敏后的邮件配置。"""
    return _sanitized(_raw_mail_config())


def save_mail_config(cfg: dict) -> dict:
    """合并写入 config.json 的 mail 段；password 明文加密，留空保留旧密文。"""
    store = get_config_store()
    full = store.load()
    section: dict[str, Any] = dict(_MAIL_DEFAULTS)
    if isinstance(full.get("mail"), dict):
        for key, value in full["mail"].items():
            if key in _MAIL_DEFAULTS:
                section[key] = value
    for key, value in (cfg or {}).items():
        if key == "password":
            if str(value or ""):
                section["password_enc"] = encrypt(str(value))
        elif key in _MAIL_DEFAULTS and key != "password_enc":
            section[key] = value
    full["mail"] = section
    store.save(full)
    return _sanitized(section)


# ---------------------------------------------------------------- 发送实现

def _plain_text(html_body: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html_body)
    return re.sub(r"\s+", " ", text).strip()


def _build_message(cfg: dict, *, to_addr: str, subject: str,
                   html_body: str, text: str = "") -> EmailMessage:
    from_name = str(cfg.get("from_name") or "瞬旅 FlashTrip")
    from_addr = str(cfg.get("from_addr") or cfg.get("user") or "")
    msg = EmailMessage()
    msg["From"] = formataddr((from_name, from_addr)) if from_addr else from_name
    msg["To"] = to_addr or ""
    msg["Subject"] = str(subject or "")
    msg["Date"] = formatdate(localtime=True)
    msg.set_content(text or _plain_text(html_body) or "请查看邮件正文。")
    msg.add_alternative(html_body, subtype="html")
    return msg


def _smtp_send(cfg: dict, recipients: list[str], msg: EmailMessage,
               *, password: str | None = None) -> None:
    """建立 SMTP 连接并投递；口令只在本地变量中出现，绝不写日志。"""
    host = str(cfg.get("host") or "").strip()
    port = int(cfg.get("port") or 465)
    timeout = float(cfg.get("timeout_s") or 10)
    use_ssl = bool(cfg.get("use_ssl"))
    use_tls = bool(cfg.get("use_tls"))
    pwd = password if password is not None else decrypt(str(cfg.get("password_enc") or ""))
    if not host:
        raise RuntimeError("SMTP 主机未配置")

    server = (smtplib.SMTP_SSL(host, port, timeout=timeout) if use_ssl
              else smtplib.SMTP(host, port, timeout=timeout))
    try:
        server.ehlo()
        if use_tls and not use_ssl:
            server.starttls()
            server.ehlo()
        user = str(cfg.get("user") or "")
        if user and pwd:
            server.login(user, pwd)
        server.send_message(msg, to_addrs=recipients)
    finally:
        try:
            server.quit()
        except Exception:
            log.warning("mail.smtp_quit_failed")


def _write_log(db, *, to_addr: str, subject: str, template: str, status: str,
               error: str, trip_id: str | None, created_by: str | None,
               sent_at: datetime | None) -> None:
    """写 mail_logs；DB 未就绪时仅告警，绝不影响发送结果。"""
    session = db
    owns = False
    if session is None:
        try:
            from app.db.session import get_session
            session = get_session()()
            owns = True
        except Exception as exc:
            log.warning("mail.log_session_unavailable", error=type(exc).__name__)
            return
    try:
        session.add(MailLog(
            to_addr=str(to_addr or ""),
            subject=str(subject or ""),
            template=template or "generic",
            status=status,
            error=error or None,
            trip_id=trip_id,
            created_by=created_by,
            sent_at=sent_at,
        ))
        session.commit()
    except Exception as exc:
        log.warning("mail.log_write_failed", error=type(exc).__name__)
        try:
            session.rollback()
        except Exception:
            log.warning("mail.log_rollback_failed")
    finally:
        if owns:
            try:
                session.close()
            except Exception:
                log.warning("mail.log_close_failed")


def send_mail(to_addr: str, subject: str, html: str, *, text: str = "", template: str = "",
              trip_id: str | None = None, created_by: str | None = None, db=None) -> dict:
    """发送一封邮件并记录日志；绝不向调用方抛异常。"""
    try:
        cfg = _raw_mail_config()
    except Exception as exc:
        log.warning("mail.config_read_failed", error=type(exc).__name__)
        cfg = dict(_MAIL_DEFAULTS)

    ok_flag = False
    error = ""
    sent_at: datetime | None = None
    try:
        if not cfg.get("enabled"):
            raise RuntimeError("邮件服务未启用")
        msg = _build_message(cfg, to_addr=to_addr, subject=subject,
                             html_body=html or "<p>通知</p>", text=text)
        _smtp_send(cfg, [to_addr], msg)
        ok_flag = True
        sent_at = datetime.now(timezone.utc)
    except Exception as exc:
        # 只记异常类型名，避免 SMTP 异常消息回显账号/口令
        error = f"邮件发送失败：{type(exc).__name__}"

    try:
        _write_log(
            db, to_addr=to_addr, subject=subject, template=template or "generic",
            status="sent" if ok_flag else "failed", error=error,
            trip_id=trip_id, created_by=created_by, sent_at=sent_at,
        )
    except Exception as exc:
        log.warning("mail.log_unexpected", error=type(exc).__name__)

    if ok_flag:
        return {"ok": True}
    return {"ok": False, "error": error}


def test_mail(override: dict | None = None) -> dict:
    """实际连 SMTP 发一封测试信；任何异常都转成 {"ok": False, "message": ...}。"""
    try:
        cfg: dict[str, Any] = dict(_MAIL_DEFAULTS)
        cfg.update(_raw_mail_config())
        for key, value in (override or {}).items():
            if key == "password":
                if str(value or ""):
                    cfg["password_enc"] = encrypt(str(value))
            elif key in _MAIL_DEFAULTS and key != "password_enc":
                cfg[key] = value
        if not str(cfg.get("host") or "").strip():
            return {"ok": False, "message": "未配置 SMTP 主机，无法发送测试邮件"}
        recipients = cfg.get("default_recipients") or []
        to_addr = str(cfg.get("from_addr") or cfg.get("user") or (recipients[0] if recipients else ""))
        if not to_addr:
            return {"ok": False, "message": "未配置收件地址（from_addr 或 user）"}
        html_body = render_template("test", {
            "app_name": cfg.get("from_name"),
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
        msg = _build_message(cfg, to_addr=to_addr, subject="瞬旅 FlashTrip 测试邮件", html_body=html_body)
        _smtp_send(cfg, [to_addr], msg)
        return {"ok": True, "message": f"测试邮件已发送至 {to_addr}"}
    except Exception as exc:
        return {"ok": False, "message": f"测试邮件发送失败：{type(exc).__name__}"}


# ---------------------------------------------------------------- 收件人与日志

def get_default_recipients(db, trip_id: str) -> list[str]:
    """行程 owner + 所有成员关联 User 的邮箱；去重、忽略空/停用/软删。"""
    out: list[str] = []
    seen: set[str] = set()

    def add(value: Any) -> None:
        email = str(value or "").strip()
        if email and email.lower() not in seen:
            seen.add(email.lower())
            out.append(email)

    try:
        from app.models.collab import TripMember
        from app.models.trip import Trip
        from app.models.user import User

        trip = db.get(Trip, trip_id)
        if trip is not None:
            owner = db.get(User, trip.owner_id)
            if owner is not None and bool(owner.is_active):
                add(owner.email)
            members = db.query(TripMember).filter(TripMember.trip_id == trip_id).all()
            user_ids = [m.user_id for m in members if m.user_id]
            if user_ids:
                users = db.query(User).filter(
                    User.id.in_(user_ids), User.is_active.is_(True)
                ).all()
                for user in users:
                    add(user.email)
            # 未绑定 User 的受邀成员可直接登记邮箱
            for member in members:
                add(getattr(member, "email", None))
    except Exception as exc:
        log.warning("mail.recipients_lookup_failed", error=type(exc).__name__)

    # 管理员在 mail 段配置的固定收件人作为兜底
    try:
        for addr in _raw_mail_config().get("default_recipients") or []:
            add(addr)
    except Exception:
        log.warning("mail.recipients_config_failed")
    return out


def list_logs(db, limit: int = 50) -> list[dict]:
    """最近邮件日志（倒序），DB 未就绪时返回空列表。"""
    try:
        rows = (
            db.query(MailLog)
            .order_by(MailLog.created_at.desc())
            .limit(max(1, min(int(limit or 50), 200)))
            .all()
        )
        out: list[dict] = []
        for row in rows:
            created = getattr(row, "created_at", None)
            out.append({
                "id": row.id,
                "to_addr": row.to_addr,
                "subject": row.subject,
                "template": row.template,
                "status": row.status,
                "error": row.error,
                "trip_id": row.trip_id,
                "created_by": row.created_by,
                "sent_at": row.sent_at.isoformat() if isinstance(row.sent_at, datetime) else None,
                "created_at": created.isoformat() if isinstance(created, datetime) else "",
            })
        return out
    except Exception as exc:
        log.warning("mail.logs_read_failed", error=type(exc).__name__)
        return []


def send_weather_advice(db, trip: dict, *, advice: str, weather: dict | None = None) -> dict:
    """给行程默认收件人发送天气建议，返回 {sent, failed}；任何失败都不抛。

    供 POST /trips/{trip_id}/weather-advice 与定时提醒共用。
    """
    trip_id = str(trip.get("trip_id") or trip.get("id") or "")
    current = (weather or {}).get("current") or {}
    summary = (
        f"{current.get('weather') or '暂无'}，{current.get('temperature', '--')}℃，"
        f"湿度 {current.get('humidity', '--')}%，{current.get('wind') or '风力未知'}"
    )
    context = {
        "trip_title": trip.get("title") or "我的行程",
        "destination": trip.get("destination") or "目的地",
        "start_date": trip.get("start_date") or "近期",
        "end_date": trip.get("end_date") or "待定",
        "weather_summary": summary,
        "advice": advice or "",
    }
    html_body = render_template("trip_weather_advice", context)
    subject = f"【出行提醒】{context['trip_title']} · 天气与装备建议"

    sent = 0
    failed = 0
    for addr in get_default_recipients(db, trip_id):
        try:
            result = send_mail(addr, subject, html_body, template="trip_weather_advice",
                               trip_id=trip_id or None, db=db)
            if result.get("ok"):
                sent += 1
            else:
                failed += 1
        except Exception as exc:
            # send_mail 契约已保证不抛，这里仅作防御性兜底
            log.warning("mail.advice_send_failed", error=type(exc).__name__)
            failed += 1
    return {"sent": sent, "failed": failed}
