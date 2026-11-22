"""通用 schema 基座与序列化辅助。

统一响应经 starlette.JSONResponse 输出（原生 json.dumps，不认识 ORM/datetime/Decimal），
因此所有 API 返回前必须用 model_dump(mode="json") 转成纯 JSON 类型。
"""
from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict

_M = TypeVar("_M", bound=BaseModel)


class ORMModel(BaseModel):
    """响应模型基类：允许从 SQLAlchemy ORM 对象直接校验。"""

    model_config = ConfigDict(from_attributes=True)


def dump(model_cls: type[_M], obj: Any) -> dict:
    """把单个 ORM 对象序列化为纯 JSON dict。"""
    return model_cls.model_validate(obj).model_dump(mode="json")


def dump_many(model_cls: type[_M], rows: Any) -> list[dict]:
    """把 ORM 对象序列/迭代器序列化为纯 JSON 列表。"""
    return [model_cls.model_validate(row).model_dump(mode="json") for row in rows]
