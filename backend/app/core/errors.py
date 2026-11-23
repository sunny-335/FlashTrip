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
    # 地图模块细分错误（2007-2010 段）
    MAP_TILE_AUTH_FAILED = 2007      # 上游瓦片鉴权/拦截类失败（tk 非法 403、CloudWAF 418 等）
    MAP_TILE_UPSTREAM_ERROR = 2008   # 上游瓦片服务不可用（5xx / 网络异常）
    MAP_SERVICE_KEY_MISSING = 2009   # 服务能力（POI / 路径规划）所需密钥未配置
    MAP_ROUTE_FAILED = 2010          # 路径规划上游失败（高德 Web 服务 v3/direction）
    # 天气/邮件/备份模块专用（2011-2013 段）
    WEATHER_CONFIG_MISSING = 2011   # 天气供应商必填配置缺失（如和风 API Host）
    MAIL_RECIPIENTS_MISSING = 2012  # 邮件收件人未配置
    BACKUP_FILE_MISSING = 2013      # 备份文件不存在（下载时语义化 404）
    # AI 链路修复专用（2014-2016 段）
    AI_TOOL_CALL_INVALID = 2014           # 模型产出的工具调用非法/未知（如文本协议里的自造工具名）
    AI_TITLE_GENERATION_FAILED = 2015     # 会话标题自动生成失败（静默回退截断标题，仅审计）
    AI_STREAM_OPTIONS_UNSUPPORTED = 2016  # 上游不识别 stream_options，已自动降级重试
    # 预算/人数联动/对象存储（2017-2020 段）
    BUDGET_INVALID = 2017           # 预算参数非法（分类缺失、金额无效）
    STORAGE_CONFIG_INVALID = 2018   # 对象存储配置不完整或后端非法
    STORAGE_UPLOAD_FAILED = 2019    # 对象存储上传/预签名失败
    DURATION_INVALID = 2020         # 行程天数联动参数非法（天数非正、缺少基准日期）
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
    ErrorCode.MAP_TILE_AUTH_FAILED: 400,
    ErrorCode.MAP_TILE_UPSTREAM_ERROR: 502,
    ErrorCode.MAP_SERVICE_KEY_MISSING: 400,
    ErrorCode.MAP_ROUTE_FAILED: 502,
    ErrorCode.WEATHER_CONFIG_MISSING: 422,
    ErrorCode.MAIL_RECIPIENTS_MISSING: 422,
    ErrorCode.BACKUP_FILE_MISSING: 404,
    ErrorCode.AI_TOOL_CALL_INVALID: 400,
    ErrorCode.AI_TITLE_GENERATION_FAILED: 502,
    ErrorCode.AI_STREAM_OPTIONS_UNSUPPORTED: 502,
    ErrorCode.BUDGET_INVALID: 422,
    ErrorCode.STORAGE_CONFIG_INVALID: 422,
    ErrorCode.STORAGE_UPLOAD_FAILED: 502,
    ErrorCode.DURATION_INVALID: 422,
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
