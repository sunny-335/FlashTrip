"""业务错误码与异常类型。"""
from __future__ import annotations


class ErrorCode:
    OK = 0
    VALIDATION = 1001
    UNAUTHORIZED = 1002
    FORBIDDEN = 1003
    NOT_FOUND = 1004
    CONFLICT = 1005
    RATE_LIMIT = 1006
    INSTALL_REQUIRED = 2001
    INSTALL_LOCKED = 2002
    DB_CONNECT_FAILED = 2003
    AI_PROVIDER_ERROR = 2004
    AI_TOOLS_DISABLED = 2005
    MAP_PROVIDER_ERROR = 2006
    INVITE_INVALID = 3001
    PASSWORD_REQUIRED = 3002
    EXPORT_UNAVAILABLE = 4001
    INTERNAL = 5000


_STATUS_BY_CODE = {
    ErrorCode.OK: 200,
    ErrorCode.VALIDATION: 422,
    ErrorCode.UNAUTHORIZED: 401,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.CONFLICT: 409,
    ErrorCode.RATE_LIMIT: 429,
    ErrorCode.INSTALL_REQUIRED: 503,
    ErrorCode.INSTALL_LOCKED: 409,
    ErrorCode.DB_CONNECT_FAILED: 503,
    ErrorCode.AI_PROVIDER_ERROR: 502,
    ErrorCode.AI_TOOLS_DISABLED: 403,
    ErrorCode.MAP_PROVIDER_ERROR: 502,
    ErrorCode.INVITE_INVALID: 400,
    ErrorCode.PASSWORD_REQUIRED: 403,
    ErrorCode.EXPORT_UNAVAILABLE: 503,
    ErrorCode.INTERNAL: 500,
}


class AppError(Exception):
    def __init__(self, code: int, message: str, detail: str | None = None, status: int | None = None):
        self.code = code
        self.message = message
        self.detail = detail
        self.status = status or _STATUS_BY_CODE.get(code, 400)
        super().__init__(message)


def http_status_to_code(status: int) -> int:
    return {
        400: ErrorCode.VALIDATION,
        401: ErrorCode.UNAUTHORIZED,
        403: ErrorCode.FORBIDDEN,
        404: ErrorCode.NOT_FOUND,
        409: ErrorCode.CONFLICT,
        422: ErrorCode.VALIDATION,
        429: ErrorCode.RATE_LIMIT,
    }.get(status, ErrorCode.INTERNAL)
