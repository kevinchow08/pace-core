import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from api.errors import BizCode, BizException
from src.auth import decode_access_token
from src.store import User, get_user_by_id

# HTTPBearer 是 FastAPI 内置的依赖：每次请求会自动读取 Authorization 请求头，
# 解析出 "Bearer <token>" 里的 token，包装成 HTTPAuthorizationCredentials 返回。
# auto_error=False：没带 token 时不直接抛 403，交给下面手动判断，返回我们自己的错误格式。
_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    # Depends(_bearer)：不是默认值，是依赖注入标记。
    # FastAPI 在处理每个请求时，会先调用 _bearer(request)，把返回值注入到 credentials 参数里。
    # 不同请求带的 token 不同，所以每次注入的结果都不一样——这跟普通默认参数（值写死不变）本质不同。
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> User:
    if credentials is None:
        raise BizException(BizCode.UNAUTHORIZED, "未登录")

    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.PyJWTError:
        raise BizException(BizCode.UNAUTHORIZED, "登录已过期，请重新登录")

    user = await get_user_by_id(payload["user_id"])
    if user is None or not user.is_active:
        raise BizException(BizCode.UNAUTHORIZED, "用户不存在或已被禁用")

    return user
