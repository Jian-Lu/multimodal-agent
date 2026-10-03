"""Harness 层 — 内置 Hook 集合。

所属层级: Harness

导入本包即触发各 hook 的装饰器注册到全局 HookManager。
"""
from app.harness.hooks.builtin import audit_logger, error_fallback, token_budget  # noqa: F401
