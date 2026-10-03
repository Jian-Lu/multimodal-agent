"""MCP Tool Schema → LangChain StructuredTool 转换。

所属层级: MCP Infrastructure

命名规则: mcp_{server_id}_{tool_name}。
inputSchema 转 Pydantic 参数模型(required 字段为必填, 否则带默认值),
保证 LLM 工具调用时能拿到结构化的参数校验。
"""
import asyncio
import concurrent.futures
import logging
from typing import Any, Awaitable, Callable, Optional

from langchain_core.tools import StructuredTool
from mcp.types import Tool
from pydantic import create_model

logger = logging.getLogger("mcp")

_JSON_TYPE_MAP = {
    "string": (str, ""),
    "integer": (int, 0),
    "number": (float, 0.0),
    "boolean": (bool, False),
    "array": (list, []),
    "object": (dict, {}),
}


def json_schema_to_pydantic(input_schema: dict[str, Any], model_name: str):
    """把 MCP JSON Schema 转成 Pydantic 参数模型(无 properties 时返回 None)。"""
    properties = (input_schema or {}).get("properties") or {}
    required = set((input_schema or {}).get("required") or [])
    if not properties:
        return None

    fields: dict[str, tuple[Any, Any]] = {}
    for fname, spec in properties.items():
        js_type = (spec or {}).get("type", "string")
        ann, default = _JSON_TYPE_MAP.get(js_type, (str, ""))
        if fname in required:
            fields[fname] = (ann, ...)
        else:
            fields[fname] = (Optional[ann], default)
    return create_model(model_name, **fields)


def mcp_tool_to_langchain(
    server_id: str,
    tool: Tool,
    call_fn: Callable[[dict], Awaitable[str]],
) -> StructuredTool:
    """把 MCP Tool 转成 LangChain StructuredTool, 命名 mcp_{server_id}_{tool_name}。

    call_fn: async (arguments: dict) -> 已格式化的文本结果。
    """
    name = f"mcp_{server_id}_{tool.name}"
    description = tool.description or tool.title or f"MCP tool `{tool.name}` (server: {server_id})"

    async def _acall(**kwargs: Any) -> str:
        return await call_fn(kwargs)

    def _call(**kwargs: Any) -> str:
        try:
            return asyncio.run(_acall(**kwargs))
        except RuntimeError:
            # 已处于运行中的事件循环: 在独立线程里开新循环执行
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                return ex.submit(asyncio.run, _acall(**kwargs)).result()

    return StructuredTool.from_function(
        func=_call,
        coroutine=_acall,
        name=name,
        description=description,
        args_schema=json_schema_to_pydantic(tool.inputSchema or {}, name),
    )
