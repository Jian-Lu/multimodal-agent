"""聊天请求 / SSE 事件模型。

所属层级: API / Schema
"""
from typing import Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """对话请求。images 为 base64 data-url 列表(Phase 2 多模态使用)。"""

    session_id: str | None = None
    message: str = Field(min_length=1)
    mode: Literal["chat", "document"] = "chat"
    images: list[str] = Field(default_factory=list)
