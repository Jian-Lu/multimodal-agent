"""MCP GitHub 客户端 — 极简集成。

所属层级: MCP Infrastructure

唯一职责: 把 GitHub MCP Server (stdio) 的工具转成 LangChain StructuredTool,
供现有 Agent 直接绑定使用。无独立 Agent 节点、无管理面板、无多 Server 动态管理。

- 传输: 仅 stdio
- 配置: 来自 .env (MCP_GITHUB_ENABLED / COMMAND / ARGS / TOKEN)
- 生命周期: init_github_mcp() 启动时连接一次, shutdown_github_mcp() 关闭时断开
- 降级: 未启用/连接失败 → 空工具列表, 现有 Agent 不受影响
- 复用 Phase 11 的 transports/tool_converter/manager, 不重复实现
"""
import logging
import os
from typing import Optional

from langchain_core.tools import StructuredTool

from app.mcp_sdk.manager import McpToolInfo, get_mcp_manager
from app.mcp_sdk.schema import McpServerConfig
from app.mcp_sdk.tool_converter import mcp_tool_to_langchain

logger = logging.getLogger("mcp.github")

_SERVER_ID = "github"


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def github_server_config() -> Optional[McpServerConfig]:
    """从 .env 读取 GitHub MCP Server 配置(MCP_GITHUB_*)。"""
    if _env("MCP_GITHUB_ENABLED", "true").strip().lower() not in ("1", "true", "yes"):
        return None
    command = _env("MCP_GITHUB_COMMAND", "npx")
    args = [
        a.strip()
        for a in _env("MCP_GITHUB_ARGS", "-y,@modelcontextprotocol/server-github").split(",")
        if a.strip()
    ]
    env: dict[str, str] = {}
    token = _env("MCP_GITHUB_TOKEN", "").strip()
    if token:
        env["GITHUB_PERSONAL_ACCESS_TOKEN"] = token
    return McpServerConfig(
        id=_SERVER_ID,
        name="GitHub MCP",
        description="GitHub 仓库/issue/PR/搜索工具",
        transport="stdio",
        command=command,
        args=args,
        env=env,
        timeout=30,
        max_retries=1,
        auto_reconnect=True,
    )


async def init_github_mcp() -> list[McpToolInfo]:
    """启动时调用一次: 连接 GitHub MCP Server 并发现工具。失败降级为空列表。"""
    cfg = github_server_config()
    if cfg is None:
        logger.info("[MCP] GitHub MCP 未启用 (检查 MCP_GITHUB_ENABLED / COMMAND)")
        return []
    try:
        client = await get_mcp_manager().connect(cfg)
        tools = [t for t in get_mcp_manager().get_all_tools() if t.server_id == _SERVER_ID]
        logger.info("[MCP] GitHub MCP 连接成功, 发现 %d 个工具", len(tools))
        return tools
    except Exception as e:  # noqa: BLE001 — 连接失败不影响主流程
        logger.warning("[MCP] GitHub MCP 连接失败, 降级为空工具列表: %s", e)
        return []


def get_github_mcp_tools() -> list[StructuredTool]:
    """返回已转换的 LangChain StructuredTool 列表; 未连接则返回空列表(优雅降级)。"""
    manager = get_mcp_manager()
    client = manager.get_client(_SERVER_ID)
    if client is None or not client.connected:
        return []
    return [
        mcp_tool_to_langchain(
            client.id,
            t,
            lambda args, _sid=client.id, _tname=t.name: manager.call_tool(_sid, _tname, args),
        )
        for t in client.tools
    ]


async def shutdown_github_mcp() -> None:
    """关闭时断开 GitHub MCP Server。"""
    await get_mcp_manager().disconnect(_SERVER_ID)
