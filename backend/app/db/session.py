"""数据库引擎与会话：SQLite WAL + busy_timeout，支持向导切换 DB 后运行时重建。"""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import resolve_database_url
from app.core.logging import get_logger

log = get_logger(__name__)

_engine: Engine | None = None
_engine_url: str = ""
_SessionLocal: sessionmaker[Session] | None = None


def _build_engine(url: str) -> Engine:
    kwargs: dict = {"pool_pre_ping": True, "future": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 5}
    engine = create_engine(url, **kwargs)

    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # noqa: ANN001
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    return engine


def get_engine() -> Engine:
    global _engine, _engine_url, _SessionLocal
    url = resolve_database_url()
    if not url:
        raise RuntimeError("数据库连接串未配置：请先完成安装向导")
    if _engine is None or _engine_url != url:
        if _engine is not None:
            _engine.dispose()
        _engine = _build_engine(url)
        _engine_url = url
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False, expire_on_commit=False)
        log.info("db.engine_ready", dialect=_engine.dialect.name)
    return _engine


def reset_engine() -> None:
    """安装向导切换数据源后调用，使后续会话使用新连接。"""
    global _engine, _engine_url, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _engine_url = ""
    _SessionLocal = None


def get_session() -> sessionmaker[Session]:
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


def get_db() -> Iterator[Session]:
    SessionLocal = get_session()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
