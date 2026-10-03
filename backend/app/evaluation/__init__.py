"""Evaluation 包 — 4 层自动化评估体系。

所属层级: Evaluation

分层 (各子模块按阶段落地):
  Layer 1  metrics_collector / timing_hook   —— 组件性能基准 (常驻采集)
  Layer 2  test_routing + routing_golden      —— 路由准确性 (Phase 18)
  Layer 3  llm_judge + output_golden          —— 输出质量   (Phase 19)
  Layer 4  test_e2e + e2e_scenarios           —— E2E 场景   (Phase 20)
  report_generator                            —— 报告汇总   (Phase 21)

注意: 本包 __init__ 不得 import 会反向依赖本包的业务模块
(llm.factory / mcp_sdk.manager / harness.supervisor), 防止循环导入。
"""
from app.evaluation.metrics_collector import (  # noqa: F401
    MetricsCollector,
    get_metrics_collector,
)


def install_metrics_telemetry() -> None:
    """启动时调用: 幂等安装 Layer 1 常驻指标采集 (TimingHook)。"""
    from app.evaluation import timing_hook

    timing_hook.install()
