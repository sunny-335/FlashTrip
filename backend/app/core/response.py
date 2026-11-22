"""统一响应包装 {code, data, message, request_id} 与全局异常处理器。"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import AppError, ErrorCode, http_status_to_code
from app.core.logging import get_logger

log = get_logger(__name__)


def _rid(request: Request | None) -> str:
    return getattr(request.state, "request_id", "") if request is not None else ""


def envelope(code: int, data: Any = None, message: str = "ok", request_id: str = "", detail: Any = None) -> dict:
    body: dict[str, Any] = {"code": code, "data": data, "message": message, "request_id": request_id}
    if detail is not None:
        body["detail"] = detail
    return body


def ok(data: Any = None, message: str = "ok", request_id: str = "") -> JSONResponse:
    return JSONResponse(envelope(ErrorCode.OK, data, message, request_id), status_code=200)


def fail(code: int, message: str, request: Request | None = None, detail: Any = None, status: int | None = None) -> JSONResponse:
    ae = AppError(code, message, detail=str(detail) if detail else None, status=status)
    return JSONResponse(
        envelope(code, None, message, _rid(request), detail),
        status_code=ae.status,
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            envelope(exc.code, None, exc.message, _rid(request), exc.detail),
            status_code=exc.status,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            envelope(ErrorCode.VALIDATION, None, "参数校验失败", _rid(request), str(exc.errors())),
            status_code=422,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = http_status_to_code(exc.status_code)
        return JSONResponse(
            envelope(code, None, str(exc.detail), _rid(request)),
            status_code=exc.status_code,
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled_exception", path=request.url.path, error=str(exc))
        return JSONResponse(
            envelope(ErrorCode.INTERNAL, None, "服务器内部错误", _rid(request), str(exc)),
            status_code=500,
        )
