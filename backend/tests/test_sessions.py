"""会话历史 — 持久化助手 + 会话端点单元测试。

沿用 test_mcp.py 的 in-memory sqlite 模式:
create_all + async_sessionmaker + 插入 User 行满足归属校验,
直接调用 chat/sessions 模块内的函数与助手, 不经过 HTTP。
"""
import asyncio

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.v1.chat import _append_message, _ensure_session
from app.api.v1.sessions import delete_session, get_session_messages, list_sessions
from app.db.base import Base
from app.models import Message, Session, User


def run(coro):
    return asyncio.run(coro)


def _make_user(user_id: str) -> User:
    return User(
        id=user_id,
        email=f"{user_id}@example.com",
        username=user_id,
        hashed_password="x",
    )


async def _setup():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _add_user(db, user_id: str) -> None:
    db.add(_make_user(user_id))
    await db.commit()


async def _row_count(db, model) -> int:
    return len((await db.scalars(select(model))).all())


async def _msgs(db, session_id: str) -> list[Message]:
    return (
        await db.scalars(select(Message).where(Message.session_id == session_id))
    ).all()


def test_chat_persist_creates_session_and_messages():
    async def _run():
        engine, maker = await _setup()
        async with maker() as db:
            await _add_user(db, "u1")
        async with maker() as db:
            await _ensure_session(db, "u1", "s1", "chat", "帮我写出一周的新闻热点")
            await _append_message(db, "s1", "assistant", "这是报告…", "u1")
        async with maker() as db:
            sess = await db.get(Session, "s1")
            assert sess is not None
            assert sess.user_id == "u1"
            assert sess.mode == "chat"
            assert sess.title == "帮我写出一周的新闻热点"
            msgs = await _msgs(db, "s1")
            assert [(m.role, m.content) for m in msgs] == [
                ("user", "帮我写出一周的新闻热点"),
                ("assistant", "这是报告…"),
            ]
        await engine.dispose()
    run(_run())


def test_ensure_session_idempotent():
    async def _run():
        engine, maker = await _setup()
        async with maker() as db:
            await _add_user(db, "u1")
        async with maker() as db:
            await _ensure_session(db, "u1", "s1", "chat", "第一问")
            await _ensure_session(db, "u1", "s1", "chat", "第二问")
        async with maker() as db:
            assert await _row_count(db, Session) == 1  # 会话不重复
            assert await _row_count(db, Message) == 2  # 每回合各落 1 条用户消息
            sess = await db.get(Session, "s1")
            assert sess.title == "第一问"  # 标题取首条, 不覆盖
        await engine.dispose()
    run(_run())


def test_ownership_guard():
    async def _run():
        engine, maker = await _setup()
        async with maker() as db:
            await _add_user(db, "u1")
            await _add_user(db, "u2")
        async with maker() as db:
            await _ensure_session(db, "u1", "s1", "chat", "A 的会话")
        # B 对 A 的会话追加消息 / 尝试创建同 id 会话 → 均不写入
        async with maker() as db:
            await _append_message(db, "s1", "assistant", "越权内容", "u2")
            await _ensure_session(db, "u2", "s1", "chat", "B 的消息")
        async with maker() as db:
            sess = await db.get(Session, "s1")
            assert sess.user_id == "u1"
            msgs = await _msgs(db, "s1")
            assert [(m.role, m.content) for m in msgs] == [("user", "A 的会话")]
        await engine.dispose()
    run(_run())


def test_list_sessions_only_own():
    async def _run():
        engine, maker = await _setup()
        async with maker() as db:
            await _add_user(db, "u1")
            await _add_user(db, "u2")
        async with maker() as db:
            await _ensure_session(db, "u1", "s1", "chat", "A1")
            await _ensure_session(db, "u2", "s3", "chat", "B1")
        async with maker() as db:
            u1 = await db.get(User, "u1")
            res = await list_sessions(user=u1, db=db)
            ids = [d["id"] for d in res["data"]]
            assert ids == ["s1"]
            assert "s3" not in ids
        await engine.dispose()
    run(_run())


def test_list_order_by_updated():
    async def _run():
        engine, maker = await _setup()
        async with maker() as db:
            await _add_user(db, "u1")
        async with maker() as db:
            await _ensure_session(db, "u1", "s1", "chat", "先")
            await _ensure_session(db, "u1", "s2", "document", "后")
        async with maker() as db:
            u1 = await db.get(User, "u1")
            res = await list_sessions(user=u1, db=db)
            ids = [d["id"] for d in res["data"]]
            assert ids == ["s2", "s1"]  # updated_at 倒序
        await engine.dispose()
    run(_run())


def test_get_messages_returns_ordered():
    async def _run():
        engine, maker = await _setup()
        async with maker() as db:
            await _add_user(db, "u1")
        async with maker() as db:
            await _ensure_session(db, "u1", "s1", "chat", "你好")
            await _append_message(db, "s1", "assistant", "回复一", "u1")
            await _append_message(db, "s1", "assistant", "回复二", "u1")
        async with maker() as db:
            u1 = await db.get(User, "u1")
            res = await get_session_messages("s1", user=u1, db=db)
            assert [m["content"] for m in res["data"]] == ["你好", "回复一", "回复二"]
            assert [m["role"] for m in res["data"]] == ["user", "assistant", "assistant"]
        await engine.dispose()
    run(_run())


def test_get_messages_404_for_other_user():
    async def _run():
        engine, maker = await _setup()
        async with maker() as db:
            await _add_user(db, "u1")
            await _add_user(db, "u2")
        async with maker() as db:
            await _ensure_session(db, "u1", "s1", "chat", "A 的会话")
        async with maker() as db:
            u2 = await db.get(User, "u2")
            with pytest.raises(HTTPException) as ei:
                await get_session_messages("s1", user=u2, db=db)
            assert ei.value.status_code == 404
        await engine.dispose()
    run(_run())


def test_delete_session_cascades():
    async def _run():
        engine, maker = await _setup()
        async with maker() as db:
            await _add_user(db, "u1")
        async with maker() as db:
            await _ensure_session(db, "u1", "s1", "chat", "你好")
            await _append_message(db, "s1", "assistant", "回复", "u1")
        async with maker() as db:
            u1 = await db.get(User, "u1")
            await delete_session("s1", user=u1, db=db)
        async with maker() as db:
            assert await db.get(Session, "s1") is None
            assert await _row_count(db, Message) == 0  # 消息随之删除
        await engine.dispose()
    run(_run())
