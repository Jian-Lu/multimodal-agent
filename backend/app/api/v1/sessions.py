"""会话历史端点 — 列表 / 消息 / 删除(多用户隔离)。

所属层级: API / v1

- 会话与消息由 chat_stream 在流式对话时写入 sessions/messages 表。
- 所有查询均按 user_id 归属过滤, 防止越权访问他人会话。
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.response import ok
from app.models import Message, Session, User
from app.schemas.session import MessageOut, SessionOut

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _session_out(s: Session) -> dict:
    return SessionOut.model_validate(s).model_dump(mode="json")


@router.get("")
async def list_sessions(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """列出当前用户的会话(按更新时间倒序)。"""
    result = await db.scalars(
        select(Session)
        .where(Session.user_id == user.id)
        .order_by(Session.updated_at.desc())
    )
    return ok([_session_out(s) for s in result.all()])


@router.get("/{session_id}/messages")
async def get_session_messages(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """取某会话的消息(先校验归属)。"""
    sess = await db.scalar(
        select(Session).where(Session.id == session_id, Session.user_id == user.id)
    )
    if sess is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    msgs = await db.scalars(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at.asc())
    )
    return ok(
        [MessageOut.model_validate(m).model_dump(mode="json") for m in msgs.all()]
    )


@router.delete("/{session_id}")
async def delete_session(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """删除会话及其消息(SQLite 默认不强制 FK, 故显式删消息)。"""
    sess = await db.scalar(
        select(Session).where(Session.id == session_id, Session.user_id == user.id)
    )
    if sess is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    await db.execute(delete(Message).where(Message.session_id == session_id))
    await db.delete(sess)
    await db.commit()
    return ok(None, message="删除成功")
