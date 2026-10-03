"""聊天端点 — SSE 流式输出 (LangGraph 多智能体)。

所属层级: API / v1

用 graph.astream_events 捕获 on_chat_model_stream 事件, 逐 token 推送。
mode: chat(通用多智能体) | document(Writer 生成 Markdown)。
流式过程中把「用户消息 + 最终答复」持久化为 Session/Message 行, 供历史会话查询。
"""
import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.validation import validate_image_base64
from app.harness.graph import get_graph
from app.models import Message, Session, User
from app.schemas.chat import ChatRequest

router = APIRouter(prefix="/chat", tags=["chat"])


def _sse(event: str, data: dict | str) -> str:
    """构造一条标准 SSE 事件。"""
    if isinstance(data, str):
        return f"event: {event}\ndata: {data}\n\n"
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _should_skip_stream(event: dict) -> bool:
    """跳过非聊天模型流, 以及 supervisor 内部路由决策流(routing tag)。"""
    if event.get("event") != "on_chat_model_stream":
        return True
    return "routing" in event.get("tags", [])


async def _append_message(
    db: AsyncSession, session_id: str, role: str, content: str, user_id: str
) -> None:
    """向会话追加一条消息; 会话不存在或归属他人则跳过(防越权)。"""
    sess = await db.get(Session, session_id)
    if sess is None or sess.user_id != user_id:
        return
    db.add(
        Message(
            session_id=session_id,
            role=role,
            content=content,
            # 显式亚秒时间: 避免 server_default(func.now) 同秒并列导致消息乱序
            created_at=datetime.now(),
        )
    )
    sess.updated_at = datetime.now()
    await db.commit()


async def _ensure_session(
    db: AsyncSession, user_id: str, session_id: str, mode: str, message: str
) -> None:
    """确保会话行存在(标题取用户消息前 20 字), 并落库本次用户消息。"""
    sess = await db.get(Session, session_id)
    if sess is None:
        title = (message.strip()[:20]) or "新对话"
        db.add(Session(id=session_id, user_id=user_id, mode=mode, title=title))
        await db.commit()
    elif sess.user_id != user_id:
        return  # 会话归属他人, 不越权写入
    await _append_message(db, session_id, "user", message, user_id)


@router.post("/stream")
async def chat_stream(
    payload: ChatRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """多智能体对话 SSE 端点 (鉴权 + 3MB 图片校验 + token 流式)。"""
    validate_image_base64(payload.images)

    graph = await get_graph()
    session_id = payload.session_id or str(uuid.uuid4())
    # 多用户隔离: thread_id 前缀 user_id, 防止不同用户同 session_id 串检查点
    thread_id = f"{user.id}:{session_id}"
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 10}
    inputs = {
        "messages": [HumanMessage(content=payload.message)],
        "mode": payload.mode,
        "images": payload.images,
    }

    await _ensure_session(db, user.id, session_id, payload.mode, payload.message)

    async def event_generator():
        chunks: list[str] = []
        yield _sse(
            "meta",
            {"session_id": session_id, "mode": payload.mode, "user": user.username},
        )
        try:
            async for event in graph.astream_events(inputs, config=config, version="v2"):
                if _should_skip_stream(event):
                    continue
                chunk = event.get("data", {}).get("chunk")
                token = getattr(chunk, "content", "")
                if token:
                    chunks.append(token)
                    yield _sse("message", {"delta": token})
        except Exception as e:  # noqa: BLE001 — 模型/沙箱异常转为友好事件
            yield _sse("error", {"message": f"{type(e).__name__}: {e}"})
        finally:
            text = "".join(chunks)
            if text:
                await _append_message(db, session_id, "assistant", text, user.id)
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
