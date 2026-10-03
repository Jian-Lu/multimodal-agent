"""Harness 层 — Token 预算检查 Hook (pre)。

所属层级: Harness

轻量统计, 不调用 LLM; 超预算时打标记, 由上层(Agent/前端)决定如何处理。
"""
import logging

from app.config import settings
from app.harness.hooks.decorators import pre_hook

logger = logging.getLogger("harness.hooks")


@pre_hook(node="*", priority=10)
async def hook_pre_token_budget(state: dict, node_name: str, config) -> dict | None:
    """估算对话 token 数, 超预算返回标记字段。"""
    messages = state.get("messages") or []
    total_chars = sum(len(str(getattr(m, "content", ""))) for m in messages)
    est_tokens = total_chars // 4
    if est_tokens > settings.HOOK_TOKEN_BUDGET:
        logger.info(
            "TokenBudgetCheck: node=%s 估算 %d tokens 超出预算 %d",
            node_name,
            est_tokens,
            settings.HOOK_TOKEN_BUDGET,
        )
        return {"token_budget_exceeded": True}
    return None
