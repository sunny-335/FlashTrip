"""对象存储抽象测试：local 不回归、oss/s3 调用参数、预签名与配置加密（外部调用全部 mock）。"""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1 import deps
from app.core.errors import AppError, ErrorCode
from app.db.base import Base
from app.models.attachment import Attachment
from app.models.trip import Trip
from app.models.user import User
from app.services import storage_service


class _MemStore:
    """内存版 ConfigStore，隔离测试对真实 config.json 的读写。"""

    def __init__(self) -> None:
        self.cfg: dict = {"installed": True}

    def load(self) -> dict:
        return dict(self.cfg)

    def save(self, cfg: dict) -> None:
        self.cfg = dict(cfg)


@pytest.fixture()
def store(monkeypatch):
    mem = _MemStore()
    monkeypatch.setattr(storage_service, "get_config_store", lambda: mem)
    return mem


_OSS_CFG = {
    "region": "oss-cn-hangzhou",
    "bucket": "my-bucket",
    "access_key_id": "AK123",
    "access_key_secret": "SK456",
}
_S3_CFG = {
    "endpoint_url": "https://minio.local",
    "region": "us-east-1",
    "bucket": "b1",
    "access_key_id": "ak",
    "access_key_secret": "sk",
}


class _FakeOssClient:
    def __init__(self) -> None:
        self.put = None
        self.presign_args = None

    def put_object(self, request):
        self.put = request

    def presign(self, request, expires=None):
        self.presign_args = (request, expires)
        return SimpleNamespace(url="https://oss.example.com/object")


class _FakeS3Client:
    def __init__(self) -> None:
        self.put: dict | None = None
        self.presign = None

    def put_object(self, **kwargs):
        self.put = kwargs

    def generate_presigned_url(self, operation, Params=None, ExpiresIn=None):
        self.presign = (operation, Params, ExpiresIn)
        return "https://s3.example.com/object"


def test_default_backend_is_local(store):
    assert storage_service.active_backend() == "local"
    cfg = storage_service.get_storage_config()
    assert cfg["backend"] == "local"
    assert cfg["oss"]["has_access_key_id"] is False


def test_save_encrypts_credentials(store):
    result = storage_service.save_storage_config({"backend": "oss", "oss": _OSS_CFG})
    assert result["backend"] == "oss"
    assert result["oss"]["has_access_key_id"] is True
    assert result["oss"]["has_access_key_secret"] is True
    assert "AK123" not in str(result)
    assert "SK456" not in str(result)

    raw = store.cfg["storage"]["oss"]
    assert raw["access_key_id_enc"].startswith("ENC:")
    assert raw["access_key_secret_enc"].startswith("ENC:")


def test_oss_put_and_presign_params(store, monkeypatch):
    storage_service.save_storage_config({"backend": "oss", "oss": _OSS_CFG})
    fake = _FakeOssClient()
    monkeypatch.setattr(storage_service, "_build_oss_client", lambda section: fake)

    storage_service.put_bytes("oss", "uploads/f/x.png", b"hello", "image/png")
    assert fake.put.bucket == "my-bucket"
    assert fake.put.key == "uploads/f/x.png"
    assert fake.put.body == b"hello"
    assert fake.put.content_type == "image/png"

    url = storage_service.presigned_url("oss", "uploads/f/x.png")
    assert url == "https://oss.example.com/object"
    request, expires = fake.presign_args
    assert request.bucket == "my-bucket"
    assert request.key == "uploads/f/x.png"
    assert expires == timedelta(days=7)


def test_s3_put_and_presign_params(store, monkeypatch):
    storage_service.save_storage_config({"backend": "s3", "s3": _S3_CFG})
    fake = _FakeS3Client()
    monkeypatch.setattr(storage_service, "_build_s3_client", lambda section: fake)

    storage_service.put_bytes("s3", "uploads/f/a.txt", b"data", "text/plain")
    assert fake.put["Bucket"] == "b1"
    assert fake.put["Key"] == "uploads/f/a.txt"
    assert fake.put["Body"] == b"data"
    assert fake.put["ContentType"] == "text/plain"

    url = storage_service.presigned_url("s3", "uploads/f/a.txt")
    assert url == "https://s3.example.com/object"
    operation, params, expires = fake.presign
    assert operation == "get_object"
    assert params == {"Bucket": "b1", "Key": "uploads/f/a.txt"}
    assert expires == storage_service.DEFAULT_TTL_SECONDS


def test_presign_ttl_is_configurable(store, monkeypatch):
    cfg = dict(_S3_CFG)
    cfg["presign_ttl_seconds"] = 3600
    storage_service.save_storage_config({"backend": "s3", "s3": cfg})
    fake = _FakeS3Client()
    monkeypatch.setattr(storage_service, "_build_s3_client", lambda section: fake)

    storage_service.presigned_url("s3", "uploads/f/a.txt")
    assert fake.presign[2] == 3600


def test_public_base_url_prefers_direct_url(store, monkeypatch):
    cfg = dict(_S3_CFG)
    cfg["public_base_url"] = "https://cdn.example.com/"
    storage_service.save_storage_config({"backend": "s3", "s3": cfg})

    def _boom(section):
        raise AssertionError("公有直链模式不应构造客户端")

    monkeypatch.setattr(storage_service, "_build_s3_client", _boom)
    assert storage_service.direct_url("s3", "uploads/f/a.png") == "https://cdn.example.com/uploads/f/a.png"


def test_incomplete_config_is_rejected(store):
    with pytest.raises(AppError) as err:
        storage_service.save_storage_config({"backend": "oss", "oss": {"region": "r"}})
    assert err.value.code == ErrorCode.STORAGE_CONFIG_INVALID
    assert "Bucket" in err.value.message


def test_invalid_backend_is_rejected(store):
    with pytest.raises(AppError) as err:
        storage_service.save_storage_config({"backend": "ftp"})
    assert err.value.code == ErrorCode.STORAGE_CONFIG_INVALID


def test_object_key_is_scoped_to_folder():
    assert storage_service.object_key("行程A", "../evil.png") == "uploads/行程A/evil.png"


# ---------------------------------------------------------------- local 上传不回归

_UPLOAD_TABLES = [Trip.__table__, User.__table__, Attachment.__table__]


@pytest.fixture()
def upload_env(client, monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine, tables=_UPLOAD_TABLES)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = Session()

    owner = User(
        id="owner-1", username="owner", password_hash="x",
        role="owner", is_active=True, must_set_password=False,
    )
    trip = Trip(id="trip-1", owner_id=owner.id, title="上传行程")
    db.add_all([owner, trip])
    db.commit()

    fake_user = SimpleNamespace(id=owner.id, role="owner", must_set_password=False)
    monkeypatch.setitem(client.app.dependency_overrides, deps.require_user, lambda: fake_user)
    monkeypatch.setitem(client.app.dependency_overrides, deps.get_db, lambda: db)
    yield SimpleNamespace(client=client, db=db, owner=owner)
    db.close()
    engine.dispose()


def test_local_upload_unchanged(upload_env):
    # 默认后端为 local：写入磁盘、storage_path 为绝对路径、响应不带对象存储 URL
    resp = upload_env.client.post(
        "/api/v1/uploads",
        files={"file": ("note.png", b"\x89PNG\r\n\x1a\nhello", "image/png")},
        data={"trip_id": "trip-1", "kind": "file"},
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()["data"]
    assert payload["backend"] == "local"
    assert "url" not in payload

    path = Path(payload["storage_path"])
    assert path.is_file()
    assert path.read_bytes().startswith(b"\x89PNG")

    attachment = upload_env.db.get(Attachment, payload["id"])
    assert attachment is not None and attachment.backend == "local"
