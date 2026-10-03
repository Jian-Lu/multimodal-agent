"""Harness 层 — 错误降级 Hook (error)。

所属层级: Harness

节点异常时告警并返回降级回复, 避免异常直接冒泡给用户。
"""
import logging

from langchain_core.messages import AIMessage

from app.harness.hooks.decorators import on_error_hook

logger = logging.getLogger("harness.hooks")

_FALLBACK_TEXT = "服务暂时不可用，请稍后重试。"


@on_error_hook(node="*", priority=100)
async def hook_error_fallback(state: dict, node_name: str, config, error: Exception) -> dict | None:
    """异常时告警 + 降级回复。"""
    logger.warning(
        "ErrorFallback: node=%s error=%s: %s", node_name, type(error).__name__, error
    )
    return {
        "messages": [AIMessage(content=_FALLBACK_TEXT)],
        "final_answer": _FALLBACK_TEXT,
        "next_agent": "finish",
    }
