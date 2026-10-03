"""MCP 集成包 — 官方 Python SDK (mcp>=1.0.0)。

所属层级: MCP Infrastructure

目录:
    config.py        全局配置 (MCP_* 环境变量 + MCP_SERVER_* 预配置)
    crypto.py        敏感字段 Fernet 加密
    schema.py        McpServerConfig 数据模型
    transports.py    stdio/sse/streamable_http 传输层
    tool_converter.py MCP Tool → LangChain StructuredTool
    manager.py       McpClientManager 核心
"""
from app.mcp_sdk.config import get_mcp_settings, mcp_settings
from app.mcp_sdk.manager import (
    McpClientManager,
    McpError,
    McpServerClient,
    McpToolInfo,
    get_mcp_manager,
)
from app.mcp_sdk.schema import McpServerConfig

__all__ = [
    "McpClientManager",
    "McpServerClient",
    "McpServerConfig",
    "McpToolInfo",
    "McpError",
    "get_mcp_manager",
    "get_mcp_settings",
    "mcp_settings",
]
