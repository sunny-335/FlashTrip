"""对象存储抽象：local（默认）/ 阿里云 OSS / 任意 S3 兼容服务。

配置存于 config.json 的 storage 段（沿用 ConfigStore），密钥经 encrypt() 存 *_enc，
并在读取一律脱敏为 has_* 布尔；明文只在构造客户端瞬间解密使用。

- local：保持原有行为，由 uploads 直接写入 data_dir()/uploads，本服务不参与；
- oss：alibabacloud-oss-v2，put_object 上传，presign 生成带签名访问链接；
- s3：boto3，endpoint_url 兼容 MinIO / R2 等，generate_presigned_url 签名。

访问链接优先使用 public_base_url（公有桶直链），否则生成预签名 URL（默认 7 天，可配）。
"""
from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from typing import Any

from app.core.config_store import get_config_store
from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger
from app.core.security import decrypt, encrypt

log = get_logger(__name__)

BACKENDS = ("local", "oss", "s3")
DEFAULT_TTL_SECONDS = 7 * 24 * 3600  # 预签名默认 7 天

_DEFAULTS: dict[str, Any] = {
    "backend": "local",
    "oss": {
        "endpoint": "",
        "region": "",
        "bucket": "",
        "access_key_id_enc": "",
        "access_key_secret_enc": "",
        "public_base_url": "",
        "presign_ttl_seconds": DEFAULT_TTL_SECONDS,
    },
    "s3": {
        "endpoint_url": "",
        "region": "",
        "bucket": "",
        "access_key_id_enc": "",
        "access_key_secret_enc": "",
        "public_base_url": "",
        "presign_ttl_seconds": DEFAULT_TTL_SECONDS,
    },
}

# 前端提交的明文字段 -> 落盘密文字段（oss / s3 共用同一命名）
_SECRET_FIELDS = {
    "access_key_id": "access_key_id_enc",
    "access_key_secret": "access_key_secret_enc",
}
_PUBLIC_FIELDS = (
    "endpoint",
    "endpoint_url",
    "region",
    "bucket",
    "public_base_url",
    "presign_ttl_seconds",
)


# ---------------------------------------------------------------- 配置读写

def _raw_config() -> dict:
    """读取含密文的内部配置（仅服务端使用）。"""
    section = get_config_store().load().get("storage")
    merged = deepcopy(_DEFAULTS)
    if isinstance(section, dict):
        backend = section.get("backend")
        if backend in BACKENDS:
            merged["backend"] = backend
        for name in ("oss", "s3"):
            part = section.get(name)
            if not isinstance(part, dict):
                continue
            for key, value in part.items():
                if key in merged[name]:
                    merged[name][key] = value
    return merged


def _redacted(name: str, section: dict) -> dict:
    out = {key: section.get(key) for key in _PUBLIC_FIELDS if key in section}
    out["has_access_key_id"] = bool(section.get("access_key_id_enc"))
    out["has_access_key_secret"] = bool(section.get("access_key_secret_enc"))
    return out


def get_storage_config() -> dict:
    """脱敏存储配置：不含任何密文/明文密钥。"""
    cfg = _raw_config()
    return {
        "backend": cfg["backend"],
        "oss": _redacted("oss", cfg["oss"]),
        "s3": _redacted("s3", cfg["s3"]),
        "default_ttl_seconds": DEFAULT_TTL_SECONDS,
    }


def _normalize_ttl(value: Any) -> int:
    try:
        ttl = int(value)
    except (TypeError, ValueError):
        raise AppError(ErrorCode.STORAGE_CONFIG_INVALID, "预签名有效期必须为整数秒") from None
    if ttl <= 0:
        raise AppError(ErrorCode.STORAGE_CONFIG_INVALID, "预签名有效期必须大于 0 秒")
    return ttl


def save_storage_config(cfg: dict) -> dict:
    """合并写入 storage 段；密钥留空保留旧密文，切换后端时校验必填项。"""
    store = get_config_store()
    full = store.load()
    current = _raw_config()

    backend = cfg.get("backend")
    if backend is not None:
        if backend not in BACKENDS:
            raise AppError(ErrorCode.STORAGE_CONFIG_INVALID, "不支持的存储后端，仅支持 local / oss / s3")
        current["backend"] = backend

    for name in ("oss", "s3"):
        incoming = cfg.get(name)
        if not isinstance(incoming, dict):
            continue
        section = current[name]
        for key, value in incoming.items():
            if key in _SECRET_FIELDS:
                if str(value or ""):
                    section[_SECRET_FIELDS[key]] = encrypt(str(value))
            elif key in ("presign_ttl_seconds",):
                section[key] = _normalize_ttl(value)
            elif key in section:
                section[key] = value

    if current["backend"] in ("oss", "s3"):
        _assert_complete(current["backend"], current[current["backend"]])

    full["storage"] = current
    store.save(full)
    return get_storage_config()


def active_backend() -> str:
    """当前生效的后端；配置异常时回退 local，保证上传不中断。"""
    backend = str(_raw_config().get("backend") or "local")
    return backend if backend in BACKENDS else "local"


# ---------------------------------------------------------------- 客户端构造

def _assert_complete(backend: str, section: dict) -> None:
    missing: list[str] = []
    if not str(section.get("bucket") or "").strip():
        missing.append("Bucket")
    if not str(section.get("access_key_id_enc") or "").strip():
        missing.append("AccessKey ID")
    if not str(section.get("access_key_secret_enc") or "").strip():
        missing.append("AccessKey Secret")
    if backend == "oss" and not str(section.get("region") or "").strip():
        missing.append("Region")
    if missing:
        raise AppError(
            ErrorCode.STORAGE_CONFIG_INVALID,
            f"对象存储配置不完整：缺少{'、'.join(missing)}",
        )


def _build_oss_client(section: dict):
    """构造阿里云 OSS 客户端（测试可 patch 本函数）。"""
    import alibabacloud_oss_v2 as oss

    ak = decrypt(str(section.get("access_key_id_enc") or ""))
    sk = decrypt(str(section.get("access_key_secret_enc") or ""))
    provider = oss.credentials.StaticCredentialsProvider(ak, sk)
    conf = oss.Config(
        region=str(section.get("region") or "") or None,
        endpoint=str(section.get("endpoint") or "") or None,
        credentials_provider=provider,
    )
    return oss.Client(conf)


def _build_s3_client(section: dict):
    """构造 S3 兼容客户端（boto3，测试可 patch 本函数）。"""
    import boto3

    kwargs: dict[str, Any] = {
        "aws_access_key_id": decrypt(str(section.get("access_key_id_enc") or "")),
        "aws_secret_access_key": decrypt(str(section.get("access_key_secret_enc") or "")),
    }
    region = str(section.get("region") or "").strip()
    if region:
        kwargs["region_name"] = region
    endpoint_url = str(section.get("endpoint_url") or "").strip()
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url
    return boto3.client("s3", **kwargs)


def _section(backend: str) -> dict:
    if backend not in ("oss", "s3"):
        raise AppError(ErrorCode.STORAGE_CONFIG_INVALID, "当前不是对象存储后端")
    section = _raw_config()[backend]
    _assert_complete(backend, section)
    return section


def object_key(folder_name: str, stored_name: str) -> str:
    """对象键：uploads/<行程文件夹>/<文件名>，与本地目录结构保持一致。"""
    folder = Path(str(folder_name or "")).name or "misc"
    filename = Path(str(stored_name or "")).name or "upload"
    return f"uploads/{folder}/{filename}"


# ---------------------------------------------------------------- 上传 / 访问链接

def put_bytes(backend: str, key: str, data: bytes, content_type: str | None = None) -> None:
    """把文件内容写入对象存储；任何上游异常统一转为中文业务错误。"""
    section = _section(backend)
    ctype = content_type or "application/octet-stream"
    try:
        if backend == "oss":
            import alibabacloud_oss_v2 as oss

            client = _build_oss_client(section)
            client.put_object(
                oss.PutObjectRequest(
                    bucket=str(section["bucket"]),
                    key=key,
                    content_type=ctype,
                    body=data,
                )
            )
        else:
            client = _build_s3_client(section)
            client.put_object(
                Bucket=str(section["bucket"]),
                Key=key,
                Body=data,
                ContentType=ctype,
            )
    except AppError:
        raise
    except Exception as exc:  # noqa: BLE001  上游 SDK 错误不外泄细节
        log.warning("storage.upload_failed", backend=backend, error=type(exc).__name__)
        raise AppError(ErrorCode.STORAGE_UPLOAD_FAILED, "对象存储上传失败，请检查存储配置") from exc


def presigned_url(backend: str, key: str) -> str:
    """生成对象读取的预签名 URL（TTL 取配置，默认 7 天）。"""
    section = _section(backend)
    ttl = _normalize_ttl(section.get("presign_ttl_seconds") or DEFAULT_TTL_SECONDS)
    try:
        if backend == "oss":
            import alibabacloud_oss_v2 as oss

            client = _build_oss_client(section)
            result = client.presign(
                oss.GetObjectRequest(bucket=str(section["bucket"]), key=key),
                expires=timedelta(seconds=ttl),
            )
            url = str(getattr(result, "url", "") or "")
        else:
            client = _build_s3_client(section)
            url = str(
                client.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": str(section["bucket"]), "Key": key},
                    ExpiresIn=ttl,
                )
                or ""
            )
    except AppError:
        raise
    except Exception as exc:  # noqa: BLE001
        log.warning("storage.presign_failed", backend=backend, error=type(exc).__name__)
        raise AppError(ErrorCode.STORAGE_UPLOAD_FAILED, "生成对象存储访问链接失败") from exc
    if not url:
        raise AppError(ErrorCode.STORAGE_UPLOAD_FAILED, "生成对象存储访问链接失败")
    return url


def direct_url(backend: str, key: str) -> str:
    """读取用访问地址：公有桶优先拼 public_base_url，否则回退预签名。"""
    section = _section(backend)
    base = str(section.get("public_base_url") or "").strip()
    if base:
        return f"{base.rstrip('/')}/{key.lstrip('/')}"
    return presigned_url(backend, key)
