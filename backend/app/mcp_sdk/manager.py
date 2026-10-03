"""McpClientManager — 多 Server 连接管理 + 工具发现 + 转换 + 缓存 + 重连。

所属层级: MCP Infrastructure

- 多 Server 连接管理 (stdio / sse / streamable_http)
- 连接时自动发现工具 (tools/list)
- MCP Tool 自动转 LangChain StructuredTool (mcp_{server_id}_{tool_name})
- 调用结果按「server+工具+参数哈希」缓存 TTL 秒
- stdio 子进程崩溃/调用失败时自动重连重试(max_retries)
"""
import asyncio
import hashlib
import json
import logging
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Optional

from langchain_core.tools import StructuredTool
from mcp.types import Tool

from app.evaluation.metrics_collector import get_metrics_collector
from app.mcp_sdk.config import mcp_settings
from app.mcp_sdk.schema import McpServerConfig
from app.mcp_sdk.tool_converter import mcp_tool_to_langchain
from app.mcp_sdk.transports import mcp_client_session

logger = logging.getLogger("mcp")


class McpError(Exception):
    """MCP 调用错误 — 统一错误格式。"""

    def __init__(self, server_id: str, detail: str) -> None:
        self.server_id = server_id
        self.detail = detail
        super().__init__(detail)

    def to_dict(self) -> dict:
        return {"error": "mcp_error", "server_id": self.server_id, "detail": self.detail}


@dataclass
class McpToolInfo:
    """面向上层(Agent/API/前端)的扁平工具描述。"""

    server_id: str
    server_name: str
    name: str                      # mcp_{server_id}_{tool_name}
    original_name: str
    description: str
    input_schema: dict


class McpServerClient:
    """单个 MCP Server 的运行态客户端。"""

    def __init__(self, cfg: McpServerConfig, result_cache_ttl: int = 300) -> None:
        self.cfg = cfg
        self.connected = False
        self.tools: list[Tool] = []
        self._session: Any = None
        self._stack: Optional[AsyncExitStack] = None
        self._result_cache: dict[str, tuple[str, float]] = {}
        self._result_cache_ttl = result_cache_ttl

    @property
    def id(self) -> str:
        return self.cfg.id

    # ---------- 生命周期 ----------
    async def connect(self) -> None:
        self._stack = AsyncExitStack()
        self._session = await self._stack.enter_async_context(mcp_client_session(self.cfg))
        tools_res = await self._session.list_tools()
        self.tools = list(tools_res.tools)
        self.connected = True
        logger.info("[MCP:%s] connected, 发现 %d 个工具", self.cfg.id, len(self.tools))

    async def disconnect(self) -> None:
        if self._stack is not None:
            await self._stack.aclose()
        self._stack = None
        self._session = None
        self.tools = []
        self.connected = False
        logger.info("[MCP:%s] disconnected", self.cfg.id)

    async def reconnect(self) -> None:
        await self.disconnect()
        await self.connect()

    # ---------- 工具调用 ----------
    async def call_tool(self, tool_name: str, arguments: dict | None = None) -> str:
        if not self.connected or self._session is None:
            raise McpError(self.cfg.id, "server 未连接")

        cache_key = self._cache_key(tool_name, arguments)
        hit = self._result_cache.get(cache_key)
        if hit and time.time() - hit[1] < self._result_cache_ttl:
            logger.info("[MCP:%s] call %s (cache hit)", self.cfg.id, tool_name)
            return hit[0]

        result = await self._session.call_tool(
            tool_name,
            arguments or {},
            read_timeout_seconds=timedelta(seconds=self.cfg.timeout),
        )
        text = self._format_result(result)
        self._result_cache[cache_key] = (text, time.time())
        logger.info("[MCP:%s] call %s ok (args=%s)", self.cfg.id, tool_name, arguments)
        return text

    @staticmethod
    def _cache_key(tool_name: str, arguments: dict | None) -> str:
        payload = json.dumps(arguments or {}, sort_keys=True, default=str)
        return hashlib.sha1(f"{tool_name}:{payload}".encode("utf-8")).hexdigest()

    @staticmethod
    def _format_result(result: Any) -> str:
        """把 CallToolResult.content 各类块统一成文本。"""
        parts: list[str] = []
        for block in result.content:
            btype = getattr(block, "type", "")
            if btype == "text":
                parts.append(getattr(block, "text", "") or "")
            elif btype == "image":
                data = getattr(block, "data", "") or ""
                mime = getattr(block, "mimeType", "image/png") or "image/png"
                parts.append(f"![mcp-image](data:{mime};base64,{data})")
            else:
                parts.append(str(block))
        joined = "\n".join(p for p in parts if p)
        return joined or "(空结果)"


class McpClientManager:
    """MCP 客户端管理器(全局单例)。"""

    def __init__(self, result_cache_ttl: int | None = None) -> None:
        self._clients: dict[str, McpServerClient] = {}
        self._result_cache_ttl = result_cache_ttl or mcp_settings.TOOL_CACHE_TTL
        self._lock = asyncio.Lock()  # 防并发 connect 竞争

    # ---------- 连接管理 ----------
    async def connect(self, cfg: McpServerConfig | dict) -> McpServerClient:
        """连接一个 server(已连接则复用)。"""
        if isinstance(cfg, dict):
            cfg = McpServerConfig.model_validate(cfg)
        async with self._lock:
            client = self._clients.get(cfg.id)
            if client and client.connected:
                return client
            if client:
                await client.disconnect()
            client = McpServerClient(cfg, self._result_cache_ttl)
            await client.connect()
            self._clients[cfg.id] = client
            return client

    async def connect_many(self, configs: list[McpServerConfig | dict]) -> list[dict]:
        """批量连接启用的 server, 单个失败不阻断其余。"""
        results = []
        for cfg in configs:
            if not getattr(cfg, "enabled", True):
                continue
            try:
                client = await self.connect(cfg)
                results.append({"server_id": client.id, "status": "connected", "tools": len(client.tools)})
            except Exception as e:  # noqa: BLE001 — 单个 server 失败不影响其他
                sid = getattr(cfg, "id", "?")
                logger.error("[MCP:%s] connect failed: %s", sid, e)
                results.append({"server_id": sid, "status": "error", "detail": str(e)})
        return results

    async def disconnect(self, server_id: str) -> bool:
        client = self._clients.pop(server_id, None)
        if client:
            await client.disconnect()
            return True
        return False

    async def disconnect_all(self) -> None:
        for cid in list(self._clients):
            await self.disconnect(cid)

    def is_connected(self, server_id: str) -> bool:
        client = self._clients.get(server_id)
        return bool(client and client.connected)

    def get_client(self, server_id: str) -> Optional[McpServerClient]:
        return self._clients.get(server_id)

    def list_connected(self) -> list[McpServerConfig]:
        return [c.cfg for c in self._clients.values() if c.connected]

    # ---------- 工具 ----------
    def get_all_tools(self) -> list[McpToolInfo]:
        infos: list[McpToolInfo] = []
        for client in self._clients.values():
            if not client.connected:
                continue
            for t in client.tools:
                infos.append(
                    McpToolInfo(
                        server_id=client.id,
                        server_name=client.cfg.name or client.id,
                        name=f"mcp_{client.id}_{t.name}",
                        original_name=t.name,
                        description=t.description or t.title or "",
                        input_schema=t.inputSchema or {},
                    )
                )
        return infos

    def get_all_langchain_tools(self) -> list[StructuredTool]:
        """把所有已连接工具转成 LangChain StructuredTool。"""
        tools: list[StructuredTool] = []
        for client in self._clients.values():
            if not client.connected:
                continue
            for t in client.tools:
                tools.append(
                    mcp_tool_to_langchain(
                        client.id,
                        t,
                        lambda args, _sid=client.id, _tname=t.name: self.call_tool(_sid, _tname, args),
                    )
                )
        return tools

    # ---------- 调用 ----------
    async def call_tool(self, server_id: str, tool_name: str, arguments: dict | None = None) -> str:
        """调用工具 (含重连重试), 并采集调用延迟指标 (mcp_call_latency)。"""
        t0 = time.perf_counter()
        try:
            result = await self._call_tool_impl(server_id, tool_name, arguments)
        except Exception as e:  # noqa: BLE001 — 无论成功与否都上报指标后原样抛出
            self._emit_call_metric(server_id, tool_name, time.perf_counter() - t0, ok=False)
            raise
        self._emit_call_metric(server_id, tool_name, time.perf_counter() - t0, ok=True)
        return result

    @staticmethod
    def _emit_call_metric(server_id: str, tool_name: str, elapsed: float, ok: bool) -> None:
        """记录 MCP 工具调用延迟 (毫秒)。指标采集异常不影响调用主流程。"""
        try:
            get_metrics_collector().record(
                "mcp_call_latency", value=elapsed * 1000,
                server=server_id, tool=tool_name, ok=str(ok).lower(),
            )
        except Exception:  # noqa: BLE001
            pass

    async def _call_tool_impl(self, server_id: str, tool_name: str, arguments: dict | None = None) -> str:
        """调用工具, 失败时按 auto_reconnect/max_retries 重连重试。"""
        client = self._clients.get(server_id)
        if client is None:
            raise McpError(server_id, "server 不存在或未连接")

        attempts = 0
        max_retries = client.cfg.max_retries if client.cfg.auto_reconnect else 0
        while True:
            try:
                return await client.call_tool(tool_name, arguments)
            except McpError:
                raise
            except Exception as e:  # noqa: BLE001 — 传输/子进程崩溃等
                attempts += 1
                if attempts > max_retries:
                    raise McpError(server_id, str(e)) from e
                logger.warning(
                    "[MCP:%s] call %s 失败(第 %d 次), 自动重连: %s",
                    server_id, tool_name, attempts, e,
                )
                try:
                    await client.reconnect()
                except Exception as re:  # noqa: BLE001
                    raise McpError(server_id, f"重连失败: {re}") from re


# 全局单例
_manager = McpClientManager()


def get_mcp_manager() -> McpClientManager:
    """获取全局 McpClientManager 单例。"""
    return _manager
