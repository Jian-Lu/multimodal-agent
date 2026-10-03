"""Harness 层 — Hook 装饰器。

所属层级: Harness

用法:
    @pre_hook("supervisor")
    async def my_hook(state, node_name, config): ...

装饰后函数会被注册进全局 HookManager, 并在函数上写入 _hook_meta 元数据。
"""
from typing import Callable

from app.harness.hooks.manager import get_hook_manager
from app.harness.hooks.types import HookType


def _register(type: HookType, node: str, priority: int, fn: Callable) -> Callable:
    get_hook_manager().register_fn(
        type=type, name=fn.__name__, fn=fn, node=node, priority=priority
    )
    setattr(fn, "_hook_meta", {"type": type, "node": node, "priority": priority})
    return fn


def pre_hook(node: str = "*", priority: int = 100):
    """pre hook 装饰器: 节点执行前触发。"""

    def deco(fn: Callable) -> Callable:
        return _register("pre", node, priority, fn)

    return deco


def post_hook(node: str = "*", priority: int = 100):
    """post hook 装饰器: 节点执行后触发。"""

    def deco(fn: Callable) -> Callable:
        return _register("post", node, priority, fn)

    return deco


def on_error_hook(node: str = "*", priority: int = 100):
    """error hook 装饰器: 节点异常时触发。"""

    def deco(fn: Callable) -> Callable:
        return _register("error", node, priority, fn)

    return deco
