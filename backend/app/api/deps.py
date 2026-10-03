"""FastAPI 依赖 — DB 会话与当前用户解析。

所属层级: API / 依赖
"""
from typing import AsyncGenerator

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.db.session import AsyncSessionLocal
from app.models import User

bearer_scheme = HTTPBearer(auto_error=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """提供异步数据库会话, 请求结束自动关闭。"""
    async with AsyncSessionLocal() as session:
        yield session


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """从 Authorization: Bearer <token> 解析当前登录用户。"""
    cred_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无效或过期的凭证",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise cred_exc

    payload = decode_token(credentials.credentials)
    if not payload or "sub" not in payload:
        raise cred_exc

    user = await db.scalar(select(User).where(User.id == payload["sub"]))
    if user is None:
        raise cred_exc
    return user
