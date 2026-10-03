"""Harness 层 — 审计日志 Hook (post)。

所属层级: Harness

纯观测: 记录节点执行的关键信息(node/thread_id/耗时/输出长度), 不修改状态。
"""
import logging

from app.harness.hooks.decorators import post_hook

logger = logging.getLogger("harness.audit")


@post_hook(node="*", priority=100)
async def hook_post_audit_logger(state: dict, node_name: str, config, result: dict) -> None:
    """记录节点执行审计信息。"""
    thread_id = None
    if isinstance(config, dict):
        thread_id = (config.get("configurable") or {}).get("thread_id")
    elapsed = config.get("_hook_elapsed_ms") if isinstance(config, dict) else None
    output_len = len(str(result)) if result else 0
    logger.info(
        "AuditLogger: node=%s thread_id=%s elapsed=%.2fms output_len=%d",
        node_name,
        thread_id,
        elapsed or 0.0,
        output_len,
    )
    return None
