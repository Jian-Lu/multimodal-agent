"""数据库会话 — 异步引擎 / sessionmaker / 建表。

所属层级: DB / 基础设施

说明: 相对路径的 SQLite URL 会解析为基于 backend/ 目录的绝对路径,
     避免因启动目录不同导致数据库文件位置漂移。
"""
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import BASE_DIR, settings


def _resolve_db_url(url: str) -> str:
    """将相对路径的 SQLite URL 解析为绝对路径(Windows 兼容)。"""
    if not url.startswith("sqlite"):
        return url
    path = url.rsplit("///", 1)[-1]
    if not Path(path).is_absolute():
        path = (BASE_DIR / path).resolve().as_posix()
        return f"sqlite+aiosqlite:///{path}"
    return url


engine = create_async_engine(
    _resolve_db_url(settings.DATABASE_URL),
    echo=settings.DEBUG,
    future=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db() -> None:
    """创建所有表(开发期)。生产建议改用 Alembic 迁移。"""
    from app.db.base import Base
    from app.models import (  # noqa: F401  (注册到 metadata)
        document,
        evaluation_run,
        mcp_server,
        message,
        session,
        skill,
        user,
    )

    # 确保 SQLite 数据目录存在
    resolved = _resolve_db_url(settings.DATABASE_URL)
    if resolved.startswith("sqlite"):
        Path(resolved.rsplit("///", 1)[-1]).parent.mkdir(parents=True, exist_ok=True)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
