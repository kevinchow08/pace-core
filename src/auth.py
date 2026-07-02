"""
密码哈希 + JWT 签发/验证。

密码：bcrypt，自动加盐，慢哈希抗暴力破解。
Token：JWT，payload 携带 user_id + role，服务端不存 session，验签名即可。
"""
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from src.config import settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


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
