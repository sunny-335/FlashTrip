"""备份服务契约：导出 zip 内容、导入往返、非法包拒绝、prune、调度幂等。"""
from __future__ import annotations

import io
import zipfile

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import config_store as cs
from app.core.config_store import ConfigStore
from app.core.errors import AppError, ErrorCode
from app.db.base import Base
from app.models.backup import BackupRecord
from app.services import backup_service as bs


@pytest.fixture()
def isolated(monkeypatch, tmp_path):
    """把 config.json / db 文件 / 备份目录全部隔离到 tmp_path。"""
    store = ConfigStore(path=tmp_path / "config.json")
    store.save({"installed": True})
    monkeypatch.setattr(cs, "_store", store)

    db_path = tmp_path / "flashtrip.db"
    engine = create_engine(
        f"sqlite:///{db_path.as_posix()}",
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[BackupRecord.__table__])
    engine.dispose()

    monkeypatch.setattr(bs, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(bs, "config_path", lambda: tmp_path / "config.json")
    monkeypatch.setattr(bs, "resolve_database_url", lambda: f"sqlite:///{db_path.as_posix()}")
    monkeypatch.setattr(bs, "_persist_record", lambda *args, **kwargs: None)
    monkeypatch.setattr(bs, "_soft_delete_record", lambda *args, **kwargs: None)
    return tmp_path


def test_create_backup_contains_config_and_db(isolated):
    info = bs.create_backup()
    assert set(info) == {"id", "filename", "size", "checksum", "created_at"}
    assert info["size"] > 0 and len(info["checksum"]) == 64
    path = isolated / "backups" / info["filename"]
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        assert "config.json" in names
        assert any(name.startswith("db/") for name in names)


def test_create_is_separate_from_download(isolated):
    """立即备份只创建文件，不回传字节；下载必须走按 id 的独立路径。"""
    info = bs.create_backup()
    # create 的返回里不含任何文件内容字段
    assert all(not isinstance(v, (bytes, bytearray)) for v in info.values())

    filename, data = bs.get_backup_bytes_by_id(info["id"])
    assert filename == info["filename"]
    assert data[:2] == b"PK"  # 合法 zip 魔数
    assert len(data) == info["size"]


def test_get_backup_bytes_by_filename(isolated):
    info = bs.create_backup()
    data = bs.get_backup_bytes(info["filename"])
    assert len(data) == info["size"]


def test_download_missing_backup_raises_404(isolated):
    with pytest.raises(AppError) as exc:
        bs.get_backup_bytes_by_id("not-exist-id")
    assert exc.value.code == ErrorCode.BACKUP_FILE_MISSING
    assert exc.value.status == 404

    with pytest.raises(AppError) as exc2:
        bs.get_backup_bytes("not-exist.zip")
    assert exc2.value.code == ErrorCode.BACKUP_FILE_MISSING


def test_import_roundtrip(isolated):
    info = bs.create_backup()
    data = (isolated / "backups" / info["filename"]).read_bytes()
    result = bs.import_backup(data)
    assert "config.json" in result["restored"]
    assert any(name.startswith("db/") for name in result["restored"])
    assert "恢复完成" in result["message"]
    assert list((isolated / "backups").glob("pre-import-*.zip"))


def test_import_rejects_invalid_archive(isolated):
    with pytest.raises(AppError) as exc:
        bs.import_backup(b"not-a-zip")
    assert exc.value.code == ErrorCode.VALIDATION

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("config.json", "{}")
    with pytest.raises(AppError) as exc:
        bs.import_backup(buffer.getvalue())  # 缺 db 文件
    assert exc.value.code == ErrorCode.VALIDATION


def test_list_and_delete(isolated):
    info = bs.create_backup()
    assert any(item["filename"] == info["filename"] for item in bs.list_backups())
    assert bs.delete_backup(info["id"])["deleted"] is True
    assert not (isolated / "backups" / info["filename"]).exists()


def test_prune_keeps_retention(isolated):
    bs.save_backup_config({"retention": 1})
    for _ in range(3):
        bs.create_backup()
    assert len(list((isolated / "backups").glob("flashtrip-*.zip"))) == 3
    assert bs.prune_backups() == 2
    assert len(list((isolated / "backups").glob("flashtrip-*.zip"))) == 1


def test_scheduler_is_idempotent():
    bs.stop_scheduler()
    bs.start_scheduler()
    first = bs._scheduler_thread
    assert first is not None
    bs.start_scheduler()
    assert bs._scheduler_thread is first  # 重复调用不重复起线程
    bs.stop_scheduler()
