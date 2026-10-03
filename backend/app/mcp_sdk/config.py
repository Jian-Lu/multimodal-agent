"""MCP 全局配置 — 环境变量覆盖 (MCP_*)。

所属层级: MCP Infrastructure

所有 MCP 相关配置支持 MCP_ 前缀环境变量覆盖。
同时支持 MCP_SERVER_{ID}_{FIELD} 形式预配置 server(可选, 也可通过管理面板添加)。
"""
import json
import logging
import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config import ENV_FILE

logger = logging.getLogger("mcp.config")

# 支持从环境变量解析的 server 字段
_SERVER_FIELDS = {
    "COMMAND", "ARGS", "URL", "TRANSPORT",
    "ENV", "HEADERS", "NAME", "DESCRIPTION",
    "TIMEOUT", "MAX_RETRIES", "ENABLED",
}


class McpSettings(BaseSettings):
    """MCP 全局配置(env_prefix=MCP_ 即读 MCP_* 环境变量)。"""

    model_config = SettingsConfigDict(
        env_prefix="MCP_",
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ENABLED: bool = True          # MCP_ENABLED: 总开关
    ENCRYPTION_KEY: str = ""      # MCP_ENCRYPTION_KEY: Fernet 密钥, 留空自动生成
    AUTO_DISCOVER: bool = True    # MCP_AUTO_DISCOVER: 启动时自动发现工具
    TOOL_CACHE_TTL: int = 300     # MCP_TOOL_CACHE_TTL: 工具调用结果缓存(秒)
    MAX_CALL_DEPTH: int = 5       # MCP_MAX_CALL_DEPTH: MCP Agent 最大工具调用深度

    def server_env_configs(self) -> list[dict]:
        """解析 MCP_SERVER_{ID}_{FIELD} 环境变量为 server 配置 dict 列表。

        例: MCP_SERVER_GITHUB_COMMAND=npx
            MCP_SERVER_GITHUB_ARGS=-y,@modelcontextprotocol/server-github
            MCP_SERVER_GITHUB_ENV={"GITHUB_TOKEN":"ghp_xxx"}
        """
        servers: dict[str, dict] = {}
        prefix = "MCP_SERVER_"
        for key, value in os.environ.items():
            if not key.startswith(prefix):
                continue
            rest = key[len(prefix):]
            if "_" not in rest:
                continue
            sid, field = rest.split("_", 1)
            if field not in _SERVER_FIELDS:
                continue
            cfg = servers.setdefault(sid.lower(), {"id": sid.lower(), "name": sid.lower()})
            try:
                if field == "ARGS":
                    cfg["args"] = json.loads(value or "[]")
                elif field == "ENV":
                    cfg["env"] = json.loads(value or "{}")
                elif field == "HEADERS":
                    cfg["headers"] = json.loads(value or "{}")
                elif field == "TIMEOUT":
                    cfg["timeout"] = int(value)
                elif field == "MAX_RETRIES":
                    cfg["max_retries"] = int(value)
                elif field == "ENABLED":
                    cfg["enabled"] = value.strip().lower() in ("1", "true", "yes")
                else:
                    cfg[field.lower()] = value
            except (json.JSONDecodeError, ValueError) as e:  # noqa: BLE001
                logger.warning("MCP_SERVER_%s_%s 配置解析失败, 已忽略: %s", sid, field, e)
                continue
        return list(servers.values())


@lru_cache
def get_mcp_settings() -> McpSettings:
    """返回缓存的 MCP 配置单例。"""
    return McpSettings()


mcp_settings = get_mcp_settings()
