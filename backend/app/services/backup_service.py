"""备份服务：标准库 zipfile + 守护线程定时，零新依赖。

归档内容：config.json、SQLite 数据库文件（含 -wal/-shm）、可选 uploads/。
导入前自动生成 pre-import-*.zip 快照，失败回滚并抛 AppError(VALIDATION)。
start_scheduler() 幂等、守护线程、启动后 60s 才首次检查，绝不产生即时副作用异常。
"""
from __future__ import annotations

import hashlib
import io
import json
import threading
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import config_path, data_dir, resolve_database_url
from app.core.config_store import get_config_store
from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger
from app.core.security import new_id
from app.models.backup import BackupRecord

log = get_logger(__name__)

_BACKUP_DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "cron_hour": 3,
    "retention": 7,
    "include_uploads": True,
}


# ---------------------------------------------------------------- 配置读写

def _raw_backup_config() -> dict:
    section = get_config_store().load().get("backup")
    merged = dict(_BACKUP_DEFAULTS)
    if isinstance(section, dict):
        for key, value in section.items():
            if key in _BACKUP_DEFAULTS:
                merged[key] = value
    return merged


def get_backup_config() -> dict:
    return dict(_raw_backup_config())


def save_backup_config(cfg: dict) -> dict:
    """合并写入 config.json 的 backup 段。"""
    store = get_config_store()
    full = store.load()
    section = dict(_BACKUP_DEFAULTS)
    if isinstance(full.get("backup"), dict):
        for key, value in full["backup"].items():
            if key in _BACKUP_DEFAULTS:
                section[key] = value
    for key, value in (cfg or {}).items():
        if key in _BACKUP_DEFAULTS:
            section[key] = value
    full["backup"] = section
    store.save(full)
    return dict(section)


# ---------------------------------------------------------------- 归档读写

def _backups_dir() -> Path:
    path = data_dir() / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _db_file() -> Path | None:
    """从 resolve_database_url() 解析 SQLite 文件路径；非 SQLite 返回 None。"""
    url = resolve_database_url()
    if not url.startswith("sqlite"):
        return None
    marker = "sqlite:///"
    rest = url[len(marker):] if url.startswith(marker) else ""
    return Path(rest) if rest else None


def _config_bytes() -> bytes:
    """读取 config.json；尚未生成时用当前配置序列化兜底，保证归档恒含它。"""
    path = config_path()
    if path.is_file():
        return path.read_bytes()
    return json.dumps(get_config_store().load(), ensure_ascii=False, indent=2).encode("utf-8")


def _collect_current() -> dict:
    """收集当前数据为 {config, db, uploads} 三组字节。"""
    payloads: dict[str, Any] = {"config": _config_bytes(), "db": {}, "uploads": {}}
    db_path = _db_file()
    if db_path and db_path.is_file():
        payloads["db"][db_path.name] = db_path.read_bytes()
        # WAL 模式下 -wal/-shm 也一并纳入，避免恢复后丢最新写入
        for suffix in ("-wal", "-shm"):
            sibling = Path(str(db_path) + suffix)
            if sibling.is_file():
                payloads["db"][sibling.name] = sibling.read_bytes()
    if _raw_backup_config().get("include_uploads"):
        root = data_dir() / "uploads"
        if root.is_dir():
            for file in root.rglob("*"):
                if file.is_file():
                    payloads["uploads"][file.relative_to(root).as_posix()] = file.read_bytes()
    return payloads


def _archive_bytes(payloads: dict) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("config.json", payloads.get("config", b"{}"))
        for name, data in (payloads.get("db") or {}).items():
            archive.writestr(f"db/{Path(name).name}", data)
        for rel, data in (payloads.get("uploads") or {}).items():
            archive.writestr(f"uploads/{rel}", data)
    return buffer.getvalue()


def _current_archive_bytes() -> bytes:
    return _archive_bytes(_collect_current())


def _read_archive(file_bytes: bytes, *, require_db: bool = True) -> dict:
    """校验并解析归档；拒绝路径穿越，缺 config.json/db 抛 VALIDATION。"""
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as archive:
            names = archive.namelist()
            for name in names:
                if name.startswith("/") or ".." in Path(name).parts:
                    raise AppError(ErrorCode.VALIDATION, "备份包包含非法路径，已拒绝导入")
            config_name = next(
                (name for name in names if name == "config.json" or name.endswith("/config.json")), None
            )
            db_names = [name for name in names if name.startswith("db/") and not name.endswith("/")]
            if not config_name or (require_db and not db_names):
                raise AppError(ErrorCode.VALIDATION, "备份包缺少 config.json 或数据库文件")
            config_data = archive.read(config_name)
            json.loads(config_data.decode("utf-8"))  # 必须是合法 JSON
            return {
                "config": config_data,
                "db": {Path(name).name: archive.read(name) for name in db_names},
                "uploads": {
                    name[len("uploads/"):]: archive.read(name)
                    for name in names
                    if name.startswith("uploads/") and not name.endswith("/")
                },
            }
    except AppError:
        raise
    except Exception:
        raise AppError(ErrorCode.VALIDATION, "备份包无效或已损坏，无法解析") from None


def _apply_archive(payloads: dict) -> list[str]:
    """把解析后的归档覆盖回磁盘，返回已恢复条目名。"""
    restored: list[str] = []
    config_path().write_bytes(payloads["config"])
    restored.append("config.json")
    db_path = _db_file()
    base_dir = db_path.parent if db_path else data_dir()
    base_dir.mkdir(parents=True, exist_ok=True)
    for name, data in (payloads.get("db") or {}).items():
        safe = Path(name).name
        (base_dir / safe).write_bytes(data)
        restored.append(f"db/{safe}")
    # 路径已在 _read_archive 校验过无穿越，这里直接按相对路径还原目录结构
    for rel, data in (payloads.get("uploads") or {}).items():
        target = data_dir() / "uploads" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        restored.append(f"uploads/{rel}")
    return restored


# ---------------------------------------------------------------- DB 记录（best-effort）

def _run_in_session(action) -> None:
    """在独立会话里执行 DB 副作用；任何失败仅告警，绝不影响备份主流程。"""
    try:
        from app.db.session import get_session
        session = get_session()()
    except Exception as exc:
        log.warning("backup.session_unavailable", error=type(exc).__name__)
        return
    try:
        action(session)
        session.commit()
    except Exception as exc:
        log.warning("backup.db_action_failed", error=type(exc).__name__)
        try:
            session.rollback()
        except Exception:
            log.warning("backup.rollback_failed")
    finally:
        try:
            session.close()
        except Exception:
            log.warning("backup.session_close_failed")


def _persist_record(info: dict) -> None:
    def action(session):
        session.add(BackupRecord(
            id=info["id"], filename=info["filename"], size=info["size"],
            kind=info["kind"], status=info["status"], checksum=info["checksum"],
            storage_path=info["storage_path"],
        ))
    _run_in_session(action)


def _soft_delete_record(backup_id: str) -> None:
    def action(session):
        row = session.get(BackupRecord, backup_id)
        if row is not None:
            row.deleted_at = datetime.now(timezone.utc)
    _run_in_session(action)


# ---------------------------------------------------------------- 对外主函数

def _unique_path(prefix: str) -> Path:
    directory = _backups_dir()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    candidate = directory / f"{prefix}-{stamp}.zip"
    if not candidate.exists():
        return candidate
    # 同一秒内重复导出：附短随机码，绝不覆盖已有备份
    return directory / f"{prefix}-{stamp}-{new_id()[:6]}.zip"


def create_backup(kind: str = "manual") -> dict:
    """打包落盘并写 backup_records，返回 {id,filename,size,checksum,created_at}。"""
    data = _current_archive_bytes()
    path = _unique_path("flashtrip")
    path.write_bytes(data)
    info = {
        "id": path.stem,
        "filename": path.name,
        "size": len(data),
        "checksum": hashlib.sha256(data).hexdigest(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "kind": kind if kind in ("manual", "scheduled", "import") else "manual",
        "status": "ok",
        "storage_path": str(path),
    }
    _persist_record(info)
    return {key: info[key] for key in ("id", "filename", "size", "checksum", "created_at")}


def get_backup_bytes(filename: str) -> bytes:
    """读取备份文件内容（按文件名）；文件不存在抛语义化 404。"""
    path = _backups_dir() / Path(filename or "").name
    if not path.is_file():
        raise AppError(ErrorCode.BACKUP_FILE_MISSING, "备份文件不存在或已被删除")
    return path.read_bytes()


def _resolve_backup_path(backup_id: str) -> Path:
    """由备份 id（文件名去扩展名）解析磁盘路径，防路径穿越。"""
    safe = Path(str(backup_id or "")).name
    return _backups_dir() / (safe if safe.endswith(".zip") else f"{safe}.zip")


def get_backup_bytes_by_id(backup_id: str) -> tuple[str, bytes]:
    """按备份 id 读取文件内容，返回 (文件名, 字节)；文件不存在抛语义化 404。"""
    path = _resolve_backup_path(backup_id)
    if not path.is_file():
        raise AppError(ErrorCode.BACKUP_FILE_MISSING, "备份文件不存在或已被删除")
    return path.name, path.read_bytes()


def list_backups() -> list[dict]:
    """按文件时间倒序列出所有备份（不依赖 DB 表，表未迁移时同样可用）。"""
    out: list[dict] = []
    for path in sorted(
        _backups_dir().glob("*.zip"),
        key=lambda p: (p.stat().st_mtime, p.name),
        reverse=True,
    ):
        stat = path.stat()
        kind = ("import" if path.name.startswith("pre-import-")
                else "manual" if path.name.startswith("flashtrip-") else "other")
        out.append({
            "id": path.stem,
            "filename": path.name,
            "size": stat.st_size,
            "kind": kind,
            "status": "ok",
            "created_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            "storage_path": str(path),
        })
    return out


def delete_backup(backup_id: str) -> dict:
    """删除指定备份文件并软删其记录。"""
    safe = Path(backup_id or "").name
    path = _backups_dir() / (safe if safe.endswith(".zip") else f"{safe}.zip")
    if not path.is_file():
        raise AppError(ErrorCode.NOT_FOUND, "备份记录不存在或已被删除")
    path.unlink()
    _soft_delete_record(path.stem)
    return {"id": path.stem, "deleted": True}


def import_backup(file_bytes: bytes) -> dict:
    """校验 -> 生成 pre-import 快照 -> 覆盖恢复；失败回滚并抛 VALIDATION。"""
    archive = _read_archive(file_bytes)
    pre_bytes = _current_archive_bytes()
    pre_path = _unique_path("pre-import")
    pre_path.write_bytes(pre_bytes)
    _persist_record({
        "id": pre_path.stem,
        "filename": pre_path.name,
        "size": len(pre_bytes),
        "checksum": hashlib.sha256(pre_bytes).hexdigest(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "kind": "import",
        "status": "ok",
        "storage_path": str(pre_path),
    })
    pre_archive = _read_archive(pre_bytes, require_db=False)
    try:
        restored = _apply_archive(archive)
    except Exception:
        try:
            _apply_archive(pre_archive)
        except Exception:
            log.warning("backup.rollback_apply_failed")
        raise AppError(ErrorCode.VALIDATION, "恢复失败，已回滚至导入前数据") from None
    return {"restored": restored, "message": f"恢复完成，导入前数据已备份为 {pre_path.name}"}


def prune_backups() -> int:
    """按 retention 保留最近 N 个 flashtrip-*.zip，返回删除数量。"""
    try:
        retention = max(1, int(_raw_backup_config().get("retention") or 7))
    except (TypeError, ValueError):
        retention = 7
    files = sorted(
        _backups_dir().glob("flashtrip-*.zip"),
        key=lambda p: (p.stat().st_mtime, p.name),
        reverse=True,
    )
    removed = 0
    for path in files[retention:]:
        try:
            path.unlink()
            _soft_delete_record(path.stem)
            removed += 1
        except OSError as exc:
            log.warning("backup.prune_delete_failed", error=type(exc).__name__)
    return removed


# ---------------------------------------------------------------- 定时守护线程

_scheduler_lock = threading.Lock()
_scheduler_thread: threading.Thread | None = None
_scheduler_stop = threading.Event()
_last_backup_date = ""


def run_daily_weather_reminders(now: datetime | None = None, db=None) -> dict:
    """对在途行程发送当日天气+出行建议邮件；同一行程同一天只发一次。

    返回 {enabled, fired, sent, failed, skipped}；单项失败不影响其它行程，
    且绝不向上抛异常（供守护线程与测试直接调用）。
    """
    from app.services import mail_service, weather_service

    now = now or datetime.now()
    reminder = weather_service.get_daily_reminder_config()
    if not reminder.get("enabled"):
        return {"enabled": False, "fired": False, "sent": 0, "failed": 0, "skipped": 0}
    # 仅在配置的发送时刻所在的这一分钟内触发（每分钟巡检一次，命中即发）
    if now.strftime("%H:%M") != reminder.get("time"):
        return {"enabled": True, "fired": False, "sent": 0, "failed": 0, "skipped": 0}
    try:
        if not mail_service.get_mail_config().get("enabled"):
            return {"enabled": True, "fired": False, "sent": 0, "failed": 0, "skipped": 0,
                    "reason": "邮件服务未启用"}
    except Exception as exc:  # noqa: BLE001  读配置失败只跳过本轮
        log.warning("backup.daily_reminder_config_failed", error=type(exc).__name__)
        return {"enabled": True, "fired": False, "sent": 0, "failed": 0, "skipped": 0}

    owns = False
    session = db
    if session is None:
        try:
            from app.db.session import get_session

            session = get_session()()
            owns = True
        except Exception as exc:  # noqa: BLE001
            log.warning("backup.daily_reminder_session_unavailable", error=type(exc).__name__)
            return {"enabled": True, "fired": False, "sent": 0, "failed": 0, "skipped": 0}

    sent = failed = skipped = 0
    day_iso = now.date().isoformat()
    try:
        for trip in weather_service.check_active_trips(session):
            trip_id = str(trip.get("trip_id") or "")
            try:
                if mail_service.daily_reminder_sent(session, trip_id, day_iso):
                    skipped += 1
                    continue
                city = str(trip.get("destination") or "")
                weather = weather_service.fetch_weather(city, db=session) if city else None
                advice = mail_service.build_default_advice(weather)
                subject = f"【今日出行】{day_iso} · {trip.get('title') or '我的行程'} · 天气与建议"
                result = mail_service.send_weather_advice(
                    session, trip, advice=advice, weather=weather,
                    template=mail_service.DAILY_TEMPLATE, subject=subject,
                )
                sent += int(result.get("sent") or 0)
                failed += int(result.get("failed") or 0)
            except Exception as exc:  # noqa: BLE001  单个行程失败不影响其它
                log.warning("backup.daily_reminder_dispatch_failed", error=type(exc).__name__)
                failed += 1
    finally:
        if owns:
            try:
                session.close()
            except Exception:
                log.warning("backup.daily_reminder_close_failed")
    return {"enabled": True, "fired": True, "sent": sent, "failed": failed, "skipped": skipped}


def _tick() -> None:
    """一次巡检：到点定时备份 + 临近出发提醒 + 在途行程每日提醒；单项失败不影响其它项。"""
    global _last_backup_date
    cfg = _raw_backup_config()
    now = datetime.now()
    today = now.date().isoformat()
    if cfg.get("enabled") and now.hour == int(cfg.get("cron_hour") or 3) and _last_backup_date != today:
        try:
            create_backup("scheduled")
            _last_backup_date = today
        except Exception as exc:
            log.warning("backup.scheduled_create_failed", error=type(exc).__name__)

    # 临近出发提醒（出发当天由「每日提醒」负责，避免同一天重复发送）
    try:
        from app.db.session import get_session
        from app.services import mail_service, weather_service

        session = get_session()()
        try:
            for trip in weather_service.check_upcoming_trips(session):
                try:
                    city = str(trip.get("destination") or "")
                    weather = weather_service.fetch_weather(city, db=session) if city else None
                    advice = mail_service.build_default_advice(weather)
                    mail_service.send_weather_advice(session, trip, advice=advice, weather=weather)
                except Exception as exc:
                    log.warning("backup.advice_dispatch_failed", error=type(exc).__name__)
        finally:
            try:
                session.close()
            except Exception:
                log.warning("backup.advice_session_close_failed")
    except Exception as exc:
        log.warning("backup.advice_tick_failed", error=type(exc).__name__)

    # 在途行程每日早晨天气邮件
    try:
        run_daily_weather_reminders(now)
    except Exception as exc:
        log.warning("backup.daily_reminder_tick_failed", error=type(exc).__name__)


def _scheduler_loop() -> None:
    # 先等待再检查：startup 调用后 60s 内不产生任何 IO 副作用
    while not _scheduler_stop.wait(60.0):
        try:
            _tick()
        except Exception as exc:
            log.warning("backup.scheduler_tick_failed", error=type(exc).__name__)


def start_scheduler() -> None:
    """幂等启动守护线程；重复调用不重复起线程，任何异常都被吞掉。"""
    global _scheduler_thread
    try:
        with _scheduler_lock:
            if _scheduler_thread is not None and _scheduler_thread.is_alive():
                return
            _scheduler_stop.clear()
            thread = threading.Thread(
                target=_scheduler_loop, name="flashtrip-backup-scheduler", daemon=True
            )
            _scheduler_thread = thread
            thread.start()
        log.info("backup.scheduler_started")
    except Exception as exc:
        log.warning("backup.scheduler_start_failed", error=type(exc).__name__)
        _scheduler_thread = None


def stop_scheduler() -> None:
    """通知守护线程停止（不 join，避免阻塞调用方）。"""
    global _scheduler_thread
    _scheduler_stop.set()
    with _scheduler_lock:
        _scheduler_thread = None
