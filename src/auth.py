"""
JWT 签发/验证。

登录身份验证交给 COROS 做（App 端直接登录 COROS，后端只验证 token 真实性），
不需要独立密码，所以这里只剩 JWT 相关逻辑。
Token：JWT，payload 携带 user_id + role，服务端不存 session，验签名即可。
"""
from datetime import datetime, timedelta, timezone

import jwt

from src.config import settings


def create_access_token(user_id: int, role: str) -> str:
    payload = {
        "user_id": user_id,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm="HS256")


def decode_access_token(token: str) -> dict:
    """过期或签名不合法时抛 jwt.PyJWTError，由调用方转换成 BizException"""
    return jwt.decode(token, settings.jwt_secret_key, algorithms=["HS256"])
