"""认证端点 — 注册 / 登录。

所属层级: API / v1
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.response import ok
from app.core.security import create_access_token, hash_password, verify_password
from app.models import User
from app.schemas.auth import LoginIn, RegisterIn
from app.schemas.user import UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


def _user_out(user: User) -> dict:
    """序列化用户(排除密码哈希)。"""
    return UserOut.model_validate(user).model_dump(mode="json")


@router.post("/register")
async def register(payload: RegisterIn, db: AsyncSession = Depends(get_db)) -> dict:
    """用户注册。"""
    exists = await db.scalar(select(User).where(User.email == payload.email))
    if exists:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="邮箱已被注册")

    user = User(
        email=payload.email,
        username=payload.username,
        hashed_password=hash_password(payload.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return ok(_user_out(user), message="注册成功")


@router.post("/login")
async def login(payload: LoginIn, db: AsyncSession = Depends(get_db)) -> dict:
    """用户登录, 签发 JWT。"""
    user = await db.scalar(select(User).where(User.email == payload.email))
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="邮箱或密码错误")

    access_token = create_access_token(user.id)
    return ok(
        {
            "access_token": access_token,
            "token_type": "bearer",
            "user": _user_out(user),
        },
        message="登录成功",
    )
