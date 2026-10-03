"""MCP GitHub 极简客户端 — 单元测试。

覆盖: 配置解析、未启用/未连接时优雅降级、token 注入环境变量。
"""
import asyncio

from app.mcp_sdk.github_client import (
    _SERVER_ID,
    get_github_mcp_tools,
    github_server_config,
    init_github_mcp,
    shutdown_github_mcp,
)


def run(coro):
    return asyncio.run(coro)


def test_config_parses_from_env(monkeypatch):
    monkeypatch.setenv("MCP_GITHUB_ENABLED", "true")
    monkeypatch.setenv("MCP_GITHUB_COMMAND", "npx")
    monkeypatch.setenv("MCP_GITHUB_ARGS", "-y,@modelcontextprotocol/server-github")
    monkeypatch.setenv("MCP_GITHUB_TOKEN", "ghp_test_token")
    cfg = github_server_config()
    assert cfg is not None
    assert cfg.id == _SERVER_ID
    assert cfg.transport == "stdio"
    assert cfg.args == ["-y", "@modelcontextprotocol/server-github"]
    assert cfg.env == {"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_test_token"}


def test_config_disabled_returns_none(monkeypatch):
    monkeypatch.setenv("MCP_GITHUB_ENABLED", "false")
    assert github_server_config() is None


def test_config_defaults_without_token(monkeypatch):
    monkeypatch.delenv("MCP_GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("MCP_GITHUB_ENABLED", "true")
    cfg = github_server_config()
    assert cfg.env == {}  # 无 token 不注入, Server 走匿名限制模式


def test_get_tools_graceful_when_not_connected():
    # 未连接 -> 空列表, 不抛错
    assert get_github_mcp_tools() == []


def test_init_shutdown_disabled_no_crash(monkeypatch):
    monkeypatch.setenv("MCP_GITHUB_ENABLED", "false")
    assert run(init_github_mcp()) == []
    run(shutdown_github_mcp())  # 无操作, 不抛错
