from enum import StrEnum

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class BizCode(StrEnum):
    # 通用 — 对应标准 HTTP 语义
    UNAUTHORIZED = "UNAUTHORIZED"               # 401 未登录 / token 无效或过期
    FORBIDDEN = "FORBIDDEN"                     # 403 已登录但无权限
    NOT_FOUND = "NOT_FOUND"                     # 404 资源不存在
    CONFLICT = "CONFLICT"                       # 409 资源冲突（如重复创建）
    VALIDATION_ERROR = "VALIDATION_ERROR"       # 422 请求体字段校验失败
    INTERNAL_ERROR = "INTERNAL_ERROR"           # 500 服务器内部错误
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE" # 503 依赖服务不可用（如 LLM 超时熔断）

    # 用户 — 比通用码更精确，供 App 做针对性处理
    USER_NOT_FOUND = "USER_NOT_FOUND"   # 404 用户不存在

    # COROS 集成 —— App 端登录 COROS，后端只验证/转发 token，不托管密码
    COROS_TOKEN_INVALID = "COROS_TOKEN_INVALID"  # 401 App 传来的 COROS token 无效或已过期，
                                                   # App 需要静默用本地 Keychain 账密重新登录 COROS 后重试


# 每个业务错误码对应的 HTTP 状态码，集中维护
_HTTP_STATUS: dict[BizCode, int] = {
    BizCode.UNAUTHORIZED: 401,
    BizCode.FORBIDDEN: 403,
    BizCode.NOT_FOUND: 404,
    BizCode.CONFLICT: 409,
    BizCode.VALIDATION_ERROR: 422,
    BizCode.INTERNAL_ERROR: 500,
    BizCode.SERVICE_UNAVAILABLE: 503,
    BizCode.USER_NOT_FOUND: 404,
    BizCode.COROS_TOKEN_INVALID: 401,
}


class BizException(Exception):
    """
    业务异常，主动 raise，由全局 handler 捕获统一处理。
    http_status 从 _HTTP_STATUS 映射表自动取，调用方只需关注业务错误码。
    """

    def __init__(self, code: BizCode, message: str):
        self.code = code
        self.message = message
        self.http_status = _HTTP_STATUS.get(code, 400)


def _error_body(code: str, message: str) -> dict:
    return {"code": code, "message": message}


def register_exception_handlers(app: FastAPI) -> None:

    @app.exception_handler(BizException)
    async def biz_exception_handler(request: Request, exc: BizException):
        """业务异常：按错误码映射的 HTTP 状态码返回"""
        return JSONResponse(
            status_code=exc.http_status,
            content=_error_body(exc.code, exc.message),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """Pydantic 请求体校验失败：提取第一条错误返回 422"""
        first = exc.errors()[0]
        field = ".".join(str(loc) for loc in first["loc"] if loc != "body")
        message = f"{field}: {first['msg']}" if field else first["msg"]
        return JSONResponse(
            status_code=422,
            content=_error_body(BizCode.VALIDATION_ERROR, message),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        """兜底：所有未预期异常返回 500，不向客户端暴露内部细节"""
        # TODO: Sentry 接入后在这里上报
        return JSONResponse(
            status_code=500,
            content=_error_body(BizCode.INTERNAL_ERROR, "服务异常，请稍后重试"),
        )
