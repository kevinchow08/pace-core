from pydantic import BaseModel, EmailStr

from fastapi import APIRouter, Depends

from api.deps import get_current_user
from api.errors import BizCode, BizException
from src import coros_client
from src.auth import create_access_token
from src.store import User, get_or_create_user

router = APIRouter()


class LoginRequest(BaseModel):
    # App 端已经用用户输入的账密直接登录过 COROS，这里只转交登录结果，
    # 不再传密码——后端从不接触明文密码。
    coros_access_token: str
    coros_user_id: str
    coros_region: str = "cn"
    # 仅用于展示，不作为身份验证依据（真正的身份来自 coros_user_id）
    email: EmailStr | None = None


class UserResponse(BaseModel):
    id: int
    email: str | None
    role: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


def _to_user_response(user: User) -> UserResponse:
    return UserResponse(id=user.id, email=user.email, role=user.role)


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest):
    auth = coros_client.build_auth(body.coros_access_token, body.coros_user_id, body.coros_region)

    # 拿 token 反查 COROS，验证是不是真的登录成功过，不是客户端伪造的
    valid = await coros_client.verify_token(auth)
    if not valid:
        raise BizException(BizCode.COROS_TOKEN_INVALID, "COROS 登录状态无效，请重新登录")

    user = await get_or_create_user(body.coros_user_id, body.email)
    token = create_access_token(user.id, user.role)
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserResponse)
async def me(
    # Depends(get_current_user)：请求进来时 FastAPI 先执行 get_current_user()，
    # 内部会再触发它自己的依赖（解析 token → 查库拿用户），最终把 User 对象注入这里。
    # 这样每个需要登录的路由只需一行声明依赖，不用各自重复"解析 token + 查用户"的逻辑。
    current_user: User = Depends(get_current_user),
):
    return _to_user_response(current_user)
