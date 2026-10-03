"""MCP Server 配置数据模型。

所属层级: MCP Infrastructure

与 McpServerRecord(DB) 通过 from_config/to_config 互转。
敏感字段(env/headers)在落库时由 McpServerRecord 负责 Fernet 加密。
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

TransportType = Literal["stdio", "sse", "streamable_http"]


class McpServerConfig(BaseModel):
    """一份 MCP Server 连接配置。"""

    id: str = Field(description="唯一标识 (如 github)")
    name: str = Field(default="", description="显示名称")
    description: str = Field(default="", description="描述")
    transport: TransportType = Field(default="stdio", description="传输类型")

    # stdio
    command: Optional[str] = Field(default=None, description="命令 (如 npx)")
    args: list[str] = Field(default_factory=list, description="参数列表")
    env: dict[str, str] = Field(default_factory=dict, description="环境变量(敏感, 加密存储)")

    # sse / streamable_http
    url: Optional[str] = Field(default=None, description="服务端点")
    headers: dict[str, str] = Field(default_factory=dict, description="请求头(敏感, 加密存储)")

    # 运行时
    enabled: bool = True
    auto_reconnect: bool = True
    timeout: int = Field(default=30, description="超时(秒)")
    max_retries: int = Field(default=3, description="最大重试次数")
    allowed_users: Optional[list[str]] = Field(default=None, description="允许调用的用户列表(空=全部)")
    require_approval: bool = Field(default=False, description="调用前是否需要审批")

    @field_validator("id")
    @classmethod
    def _normalize_id(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if not v:
            raise ValueError("server id 不能为空")
        if not all(c.isalnum() or c in "_-" for c in v):
            raise ValueError("server id 仅允许字母/数字/_/-")
        return v

    @field_validator("transport", mode="before")
    @classmethod
    def _normalize_transport(cls, v: str) -> str:
        t = (v or "stdio").lower()
        if t not in ("stdio", "sse", "streamable_http"):
            raise ValueError(f"不支持的传输类型: {t}")
        return t
