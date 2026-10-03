"""Harness 层 — 生命周期管理 (超时 / 熔断)。

所属层级: Harness
"""
import asyncio
from typing import Any, Awaitable


async def with_timeout(coro: Awaitable[Any], seconds: int) -> Any:
    """给协程加超时, 超时抛 asyncio.TimeoutError。"""
    return await asyncio.wait_for(coro, timeout=seconds)


class CircuitBreaker:
    """简单熔断器: 连续失败达到阈值后打开, 拒绝后续调用。"""

    def __init__(self, failure_threshold: int = 5) -> None:
        self.failure_threshold = failure_threshold
        self.failures = 0
        self.open = False

    def record_success(self) -> None:
        self.failures = 0
        self.open = False

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.failure_threshold:
            self.open = True

    def allow(self) -> bool:
        return not self.open
