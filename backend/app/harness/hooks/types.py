"""Harness 层 — Hook 类型定义。

所属层级: Harness

Hook 签名约定:
- pre   : async (state, node_name, config) -> Optional[dict]
- post  : async (state, node_name, config, result) -> Optional[dict]
- error : async (state, node_name, config, error) -> Optional[dict]

返回值 dict 会被浅合并进 state/result; 返回 None 表示不修改。
"""
from dataclasses import dataclass
from typing import Awaitable, Callable, Literal, Optional

HookType = Literal["pre", "post", "error"]

# Hook 函数: 统一 async, 返回 Optional[dict]
HookFn = Callable[..., Awaitable[Optional[dict]]]


@dataclass
class Hook:
    """单个 Hook 的元数据。"""

    name: str
    type: HookType
    fn: HookFn
    node: str = "*"        # 目标节点, "*" 表示所有节点
    priority: int = 100    # 执行顺序, 越小越先执行
    enabled: bool = True
