"""Harness 层 — HookManager：Hook 注册、排序、执行链与节点包装。

所属层级: Harness

Hook 只做轻量逻辑(禁止调用 LLM、不阻塞事件循环), 异常被捕获仅告警,
不影响主流程; 只有 error hook 返回降级结果时才会替换节点输出。
"""
import inspect
import logging
import time
from typing import Any, Callable, Optional

from langchain_core.runnables import RunnableConfig

from app.harness.hooks.types import Hook, HookFn, HookType

logger = logging.getLogger("harness.hooks")


class HookManager:
    """管理 Hook 的注册与执行。"""

    def __init__(self) -> None:
        self._hooks: list[Hook] = []

    # ---------- 注册 ----------
    def register(self, hook: Hook) -> None:
        """注册一个 Hook。"""
        self._hooks.append(hook)

    def register_fn(
        self,
        type: HookType,
        name: str,
        fn: HookFn,
        node: str = "*",
        priority: int = 100,
    ) -> None:
        """以函数直接注册 Hook。"""
        self.register(Hook(name=name, type=type, fn=fn, node=node, priority=priority))

    def unregister(self, name: str) -> None:
        """按名字移除 Hook。"""
        self._hooks = [h for h in self._hooks if h.name != name]

    # ---------- 查询 ----------
    def hooks_for(self, type: HookType, node: str) -> list[Hook]:
        """返回匹配某类型 + 目标节点的 Hook(按 priority 升序)。"""
        matched = [
            h
            for h in self._hooks
            if h.type == type and h.enabled and (h.node == "*" or h.node == node)
        ]
        return sorted(matched, key=lambda h: h.priority)

    # ---------- 执行链 ----------
    async def run_pre(self, state: dict, node_name: str, config: Optional[dict]) -> dict:
        """依次执行 pre hook, dict 返回值浅合并进 state。"""
        for h in self.hooks_for("pre", node_name):
            try:
                mod = await h.fn(state, node_name, config)
                if isinstance(mod, dict):
                    state = {**state, **mod}
            except Exception as e:  # noqa: BLE001 — hook 异常不中断主流程
                logger.warning("pre hook %s 执行失败: %s", h.name, e)
        return state

    async def run_post(
        self, state: dict, node_name: str, config: Optional[dict], result: dict
    ) -> dict:
        """依次执行 post hook, dict 返回值浅合并进 result。"""
        for h in self.hooks_for("post", node_name):
            try:
                mod = await h.fn(state, node_name, config, result)
                if isinstance(mod, dict):
                    result = {**result, **mod}
            except Exception as e:  # noqa: BLE001
                logger.warning("post hook %s 执行失败: %s", h.name, e)
        return result

    async def run_error(
        self, state: dict, node_name: str, config: Optional[dict], error: Exception
    ) -> Optional[dict]:
        """依次执行 error hook, 首个非 None 返回值作为降级结果。"""
        for h in self.hooks_for("error", node_name):
            try:
                mod = await h.fn(state, node_name, config, error)
                if isinstance(mod, dict):
                    return mod
            except Exception as e:  # noqa: BLE001
                logger.warning("error hook %s 执行失败: %s", h.name, e)
        return None

    # ---------- 节点包装 ----------
    def wrap(self, node_fn: Callable[..., Any], node_name: str) -> Callable[..., Any]:
        """包装节点函数, 注入 pre/post/error hook 执行链。

        config 参数用 RunnableConfig 注解, 使 LangGraph 自动注入 config(含 thread_id)。
        同时兼容同步/异步节点函数。
        """

        async def wrapped(state: dict, config: Optional[RunnableConfig] = None) -> dict:
            t0 = time.perf_counter()
            state = await self.run_pre(state, node_name, config)
            try:
                result = node_fn(state)
                if inspect.isawaitable(result):
                    result = await result
            except Exception as e:
                fallback = await self.run_error(state, node_name, config, e)
                if fallback is not None:
                    return fallback
                raise
            # 注入耗时, 供 post hook(审计) 使用
            cfg = dict(config) if config else {}
            cfg["_hook_elapsed_ms"] = (time.perf_counter() - t0) * 1000
            return await self.run_post(state, node_name, cfg, result)

        wrapped.__name__ = f"hooked_{node_name}"
        return wrapped


# 全局单例
_manager = HookManager()


def get_hook_manager() -> HookManager:
    """获取全局 HookManager 单例。"""
    return _manager
