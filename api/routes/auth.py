from pydantic import BaseModel, EmailStr, Field

from fastapi import APIRouter, Depends

from api.deps import get_current_user
from api.errors import BizCode, BizException
from src.auth import create_access_token, hash_password, verify_password
from src.store import User, create_user, get_user_by_email

router = APIRouter()


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: int
    email: str
    role: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


def _to_user_response(user: User) -> UserResponse:
    return UserResponse(id=user.id, email=user.email, role=user.role)


@router.post("/register", status_code=201, response_model=UserResponse)
async def register(body: RegisterRequest):
    existing = await get_user_by_email(body.email)
    if existing is not None:
        raise BizException(BizCode.EMAIL_EXISTS, "该邮箱已注册")

    user = await create_user(body.email, hash_password(body.password))
    return _to_user_response(user)


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest):
    user = await get_user_by_email(body.email)
    if user is None:
        raise BizException(BizCode.USER_NOT_FOUND, "账号不存在")

    if not verify_password(body.password, user.password_hash):
        raise BizException(BizCode.PASSWORD_WRONG, "密码错误")

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
