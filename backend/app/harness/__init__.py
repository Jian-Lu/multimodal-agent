"""Harness 层 — 编排 (LangGraph StateGraph + Supervisor 路由 + 生命周期)。

所属层级: Harness

Phase 2 实现:
- state.py      : AgentState (messages / next_agent / iteration_count)
- supervisor.py : Supervisor 路由节点 (递归限制 ≤10)
- lifecycle.py  : 超时 / 熔断
- graph.py      : StateGraph 编译 + AsyncSqliteSaver
"""
