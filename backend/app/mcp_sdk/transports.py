"""MCP 传输层 — stdio / sse / streamable_http 连接上下文。

所属层级: MCP Infrastructure

对外只暴露 mcp_client_session(cfg): 一个进入后已完成 initialize 的 ClientSession。
统一适配三种传输, 兼容 streamable_http 返回 (read, write, get_session_id) 三元组。
"""
import logging
import os
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any, AsyncIterator, Tuple

from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.types import Tool  # noqa: F401  # re-export 供调用方使用

from app.mcp_sdk.schema import McpServerConfig

logger = logging.getLogger("mcp")

try:
    from mcp.client.streamable_http import streamable_http_client
    HAS_HTTP = True
except ImportError:  # mcp 版本过低
    HAS_HTTP = False

Streams = Tuple[Any, Any]


@asynccontextmanager
async def _streams(cfg: McpServerConfig) -> AsyncIterator[Streams]:
    """建立传输层 (read_stream, write_stream), 退出时自动清理。"""
    if cfg.transport == "stdio":
        if not cfg.command:
            raise ValueError(f"[MCP:{cfg.id}] stdio 传输必须配置 command")
        params = StdioServerParameters(
            command=cfg.command,
            args=cfg.args or None,
            # stdio 子进程需继承当前环境, 再叠加自定义 env
            env={**os.environ, **cfg.env} if cfg.env else None,
            encoding="utf-8",
            encoding_error_handler="strict",
        )
        async with stdio_client(params) as streams:
            yield streams[0], streams[1]
    elif cfg.transport == "sse":
        if not cfg.url:
            raise ValueError(f"[MCP:{cfg.id}] sse 传输必须配置 url")
        async with sse_client(
            cfg.url,
            headers=cfg.headers or None,
            timeout=cfg.timeout,
        ) as streams:
            yield streams[0], streams[1]
    elif cfg.transport == "streamable_http":
        if not HAS_HTTP:
            raise RuntimeError(f"[MCP:{cfg.id}] streamable_http 传输不可用: 请升级 mcp 版本")
        if not cfg.url:
            raise ValueError(f"[MCP:{cfg.id}] streamable_http 传输必须配置 url")
        http_client = None
        try:
            if cfg.headers:
                import httpx
                http_client = httpx.AsyncClient(headers=cfg.headers, timeout=cfg.timeout)
            async with streamable_http_client(cfg.url, http_client=http_client) as streams:
                # streamable_http 返回三元组, 只取前两个
                yield streams[0], streams[1]
        finally:
            if http_client is not None:
                await http_client.aclose()
    else:  # pragma: no cover — schema 校验已限制
        raise ValueError(f"[MCP:{cfg.id}] 不支持的传输: {cfg.transport}")


@asynccontextmanager
async def mcp_client_session(cfg: McpServerConfig) -> AsyncIterator[ClientSession]:
    """建立已初始化(initialize)的 MCP 会话。"""
    async with _streams(cfg) as (read, write):
        async with ClientSession(
            read,
            write,
            read_timeout_seconds=timedelta(seconds=cfg.timeout),
        ) as session:
            await session.initialize()
            logger.info("[MCP:%s] initialize ok (transport=%s)", cfg.id, cfg.transport)
            yield session
