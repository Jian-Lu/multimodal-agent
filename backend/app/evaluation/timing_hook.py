"""Evaluation 层 — TimingHook (Layer 1 性能基准采集)。

所属层级: Evaluation / Layer 1

利用 HookManager.wrap 已注入 config["_hook_elapsed_ms"] (pre+node 总耗时),
post 阶段无需自计时, 直接把耗时写入统一 MetricsCollector (hook_latency)。
纯观测: 不修改 state/result。异常仅告警, 不影响主流程。

注册为幂等 install(): 先 unregister 同名再 register, 重复 import / reload 安全。
"""
import logging

from app.evaluation.metrics_collector import get_metrics_collector
from app.harness.hooks.manager import get_hook_manager

logger = logging.getLogger("evaluation.timing")

HOOK_NAME = "hook_post_timing_metrics"


async def hook_post_timing_metrics(state: dict, node_name: str, config, result: dict):
    """post hook: 读取节点耗时写入指标收集器。"""
    try:
        elapsed = None
        thread_id = None
        if isinstance(config, dict):
            elapsed = config.get("_hook_elapsed_ms")
            thread_id = (config.get("configurable") or {}).get("thread_id")
        if elapsed is None:
            return None
        get_metrics_collector().record(
            "hook_latency",
            value=float(elapsed),
            node=node_name,
            thread_id=thread_id or "",
        )
    except Exception as e:  # noqa: BLE001 — hook 异常不中断主流程
        logger.warning("TimingHook 记录失败: %s", e)
    return None


def install() -> None:
    """幂等注册 TimingHook 到全局 HookManager (始终采集)。"""
    manager = get_hook_manager()
    manager.unregister(HOOK_NAME)
    manager.register_fn(
        type="post", name=HOOK_NAME, fn=hook_post_timing_metrics, node="*", priority=100
    )
    logger.info("TimingHook %s 已注册 (hook_latency 采集开启)", HOOK_NAME)
