"""MCP Infrastructure — Phase 11 单元测试。

覆盖: 加密/解密回环、schema 校验、环境变量预配置解析、
Tool→LangChain 转换、DB 加密落库、调用结果缓存、
McpError 统一格式、stdio 端到端(真实 FastMCP 子进程)。
"""
import asyncio
import sys

import pytest

from app.mcp_sdk.crypto import decrypt_dict, decrypt_text, encrypt_dict, encrypt_text
from app.mcp_sdk.manager import McpError, McpServerClient
from app.mcp_sdk.schema import McpServerConfig
from app.mcp_sdk.tool_converter import json_schema_to_pydantic, mcp_tool_to_langchain


def run(coro):
    return asyncio.run(coro)


# ---------- 1. 加密/解密 ----------
def test_crypto_text_roundtrip():
    tok = encrypt_text("ghp_secret_123")
    assert tok != "ghp_secret_123"
    assert "secret" not in tok
    assert decrypt_text(tok) == "ghp_secret_123"


def test_crypto_bad_token_returns_empty():
    assert decrypt_text("") == ""
    assert decrypt_text("not-a-valid-fernert-token") == ""


def test_crypto_dict_roundtrip():
    d = {"GITHUB_TOKEN": "ghp_x", "KEY": "v"}
    tok = encrypt_dict(d)
    assert decrypt_dict(tok) == d
    assert decrypt_dict("garbage") == {}
    assert decrypt_dict("") == {}


# ---------- 2. Schema 校验 ----------
def test_schema_id_normalization():
    cfg = McpServerConfig(id="  GitHub ", transport="SSE")
    assert cfg.id == "github"
    assert cfg.transport == "sse"


def test_schema_invalid_id_raises():
    with pytest.raises(ValueError):
        McpServerConfig(id="my server!")


def test_schema_transport_validation():
    with pytest.raises(ValueError):
        McpServerConfig(id="x", transport="websocket")


def test_schema_full_config_defaults():
    cfg = McpServerConfig(id="gh", transport="stdio", command="npx", args=["-y", "srv"])
    assert cfg.enabled is True
    assert cfg.auto_reconnect is True
    assert cfg.timeout == 30
    assert cfg.max_retries == 3
    assert cfg.allowed_users is None
    assert cfg.require_approval is False


# ---------- 3. 环境变量预配置解析 ----------
def test_server_env_configs(monkeypatch):
    from app.mcp_sdk.config import get_mcp_settings

    monkeypatch.setenv("MCP_SERVER_GITHUB_COMMAND", "npx")
    monkeypatch.setenv("MCP_SERVER_GITHUB_ARGS", '["-y","@modelcontextprotocol/server-github"]')
    monkeypatch.setenv("MCP_SERVER_GITHUB_ENV", '{"GITHUB_TOKEN":"x"}')
    cfgs = get_mcp_settings().server_env_configs()
    assert len(cfgs) == 1
    assert cfgs[0]["id"] == "github"
    assert cfgs[0]["name"] == "github"
    assert cfgs[0]["args"] == ["-y", "@modelcontextprotocol/server-github"]
    assert cfgs[0]["env"] == {"GITHUB_TOKEN": "x"}


# ---------- 4. Tool → LangChain 转换 ----------
def _fake_tool():
    from mcp.types import Tool

    return Tool(
        name="get_issues",
        description="获取仓库 issues",
        inputSchema={
            "type": "object",
            "properties": {"repo": {"type": "string", "description": "仓库名"}},
            "required": ["repo"],
        },
    )


def test_tool_converter_name_and_async_call():
    async def call_fn(args):
        return f"issues:{args['repo']}"

    lc = mcp_tool_to_langchain("github", _fake_tool(), call_fn)
    assert lc.name == "mcp_github_get_issues"
    assert "issues" in lc.description
    assert run(lc.ainvoke({"repo": "langchain"})) == "issues:langchain"


def test_tool_converter_sync_call():
    async def call_fn(args):
        return f"issues:{args['repo']}"

    lc = mcp_tool_to_langchain("github", _fake_tool(), call_fn)
    # 同步路径: 不在事件循环中, 内部 asyncio.run 起新循环
    assert lc.invoke({"repo": "sync"}) == "issues:sync"


def test_json_schema_to_pydantic():
    model = json_schema_to_pydantic(
        {
            "properties": {
                "repo": {"type": "string"},
                "limit": {"type": "integer"},
                "labels": {"type": "array"},
            },
            "required": ["repo"],
        },
        "IssuesArgs",
    )
    assert model.model_fields["repo"].is_required()
    assert not model.model_fields["limit"].is_required()
    assert model.model_fields["limit"].default == 0
    assert json_schema_to_pydantic({}, "Empty") is None


# ---------- 5. DB 加密落库回环 ----------
def test_db_record_encrypt_roundtrip():
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.db.base import Base
    from app.models.mcp_server import McpServerRecord

    async def _run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        Session = async_sessionmaker(engine, expire_on_commit=False)

        cfg = McpServerConfig(
            id="gh",
            transport="sse",
            url="http://mcp.example.com/sse",
            headers={"Authorization": "Bearer secret-token"},
            env={"GITHUB_TOKEN": "ghp_abc"},
        )
        async with Session() as db:
            db.add(McpServerRecord.from_config(cfg))
            await db.commit()

        async with Session() as db:
            row = (await db.execute(select(McpServerRecord))).scalar_one()
            # 明文绝不落库
            assert "ghp_abc" not in row.env_encrypted
            assert "secret-token" not in row.headers_encrypted
            loaded = row.to_config()
            assert loaded.env == {"GITHUB_TOKEN": "ghp_abc"}
            assert loaded.headers == {"Authorization": "Bearer secret-token"}
            assert loaded.url == "http://mcp.example.com/sse"
        await engine.dispose()

    run(_run())


# ---------- 6. 调用结果缓存 ----------
class _FakeSession:
    def __init__(self):
        self.count = 0

    async def call_tool(self, name, arguments, **kwargs):
        self.count += 1
        from mcp.types import CallToolResult, TextContent

        return CallToolResult(content=[TextContent(type="text", text="ok")], isError=False)


def test_call_tool_result_cache():
    client = McpServerClient(McpServerConfig(id="c1"), result_cache_ttl=300)
    client.connected = True
    client._session = _FakeSession()

    async def _run():
        r1 = await client.call_tool("t", {"x": 1})
        r2 = await client.call_tool("t", {"x": 1})  # 命中缓存
        r3 = await client.call_tool("t", {"x": 2})  # 不同参数 -> 新调用
        return client._session.count, r1, r2, r3

    count, r1, r2, r3 = run(_run())
    assert count == 2
    assert r1 == r2 == r3 == "ok"


def test_call_tool_unconnected_raises():
    client = McpServerClient(McpServerConfig(id="c1"))
    with pytest.raises(McpError):
        run(client.call_tool("t", {}))
    assert client._session is None


# ---------- 7. 统一错误格式 ----------
def test_mcp_error_to_dict():
    e = McpError("gh", "boom")
    assert e.to_dict() == {"error": "mcp_error", "server_id": "gh", "detail": "boom"}


# ---------- 8. stdio 端到端(真实 FastMCP 子进程) ----------
_SERVER_SOURCE = """\
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("echo-server")


@mcp.tool()
def add(a: int, b: int) -> int:
    \"\"\"两数相加\"\"\"
    return a + b


@mcp.tool()
def get_version() -> str:
    \"\"\"返回服务版本\"\"\"
    return "test-mcp-1.0.0"


@mcp.tool()
def uppercase(text: str) -> str:
    \"\"\"转大写\"\"\"
    return text.upper()


if __name__ == "__main__":
    mcp.run(transport="stdio")
"""


def test_stdio_end_to_end(tmp_path):
    from app.mcp_sdk.manager import McpClientManager

    script = tmp_path / "echo_server.py"
    script.write_text(_SERVER_SOURCE, encoding="utf-8")

    cfg = McpServerConfig(
        id="echo",
        name="Echo",
        transport="stdio",
        command=sys.executable,
        args=[str(script)],
        timeout=30,
        max_retries=1,
    )

    async def _run():
        mgr = McpClientManager(result_cache_ttl=0)
        c1 = await mgr.connect(cfg)
        c2 = await mgr.connect(cfg)  # 重复连接复用
        assert c1 is c2

        infos = mgr.get_all_tools()
        assert {i.original_name for i in infos} == {"add", "get_version", "uppercase"}
        assert all(i.name.startswith("mcp_echo_") for i in infos)

        r = await mgr.call_tool("echo", "add", {"a": 1, "b": 2})
        assert "3" in r
        r2 = await mgr.call_tool("echo", "uppercase", {"text": "hello"})
        assert "HELLO" in r2
        r3 = await mgr.call_tool("echo", "get_version", {})
        assert "test-mcp-1.0.0" in r3

        # LangChain 工具绑定
        lc_tools = mgr.get_all_langchain_tools()
        assert {t.name for t in lc_tools} == {
            "mcp_echo_add",
            "mcp_echo_get_version",
            "mcp_echo_uppercase",
        }
        await mgr.disconnect_all()
        assert mgr.list_connected() == []

    run(_run())


def test_manager_call_unconnected_raises():
    from app.mcp_sdk.manager import McpClientManager

    mgr = McpClientManager(result_cache_ttl=0)
    with pytest.raises(McpError):
        run(mgr.call_tool("ghost", "anything", {}))
