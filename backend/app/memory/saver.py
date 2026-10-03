"""Memory 层 — LangGraph 检查点存储 (AsyncSqliteSaver)。

所属层级: Memory

使用 aiosqlite 直连方式构造, 避免依赖 AsyncSqliteSaver.from_conn_string
在不同 langgraph 版本间的签名差异。
"""
from pathlib import Path

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.config import BASE_DIR, settings


def _db_path() -> str:
    """检查点 SQLite 文件绝对路径。"""
    path = settings.CHECKPOINT_DB_PATH
    if not Path(path).is_absolute():
        path = (BASE_DIR / path).resolve()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return str(path)


async def create_saver() -> AsyncSqliteSaver:
    """创建并初始化异步 SQLite 检查点存储。"""
    conn = await aiosqlite.connect(_db_path())
    saver = AsyncSqliteSaver(conn)
    await saver.setup()
    return saver
