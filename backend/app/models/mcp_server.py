"""McpServerRecord 模型 — MCP Server 配置(数据库存储, 敏感字段加密)。

所属层级: DB / 数据模型

env/headers 中的敏感值(API Token 等)以 Fernet 加密后的 JSON 字符串存储,
落库字段 env_encrypted / headers_encrypted, 明文绝不落库。
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.mcp_sdk.crypto import decrypt_dict, encrypt_dict
from app.mcp_sdk.schema import McpServerConfig


class McpServerRecord(Base):
    __tablename__ = "mcp_servers"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    description: Mapped[str] = mapped_column(String(512), default="")
    transport: Mapped[str] = mapped_column(String(32), default="stdio")

    # stdio
    command: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    args: Mapped[list] = mapped_column(JSON, default=list)
    env_encrypted: Mapped[str] = mapped_column(Text, default="")  # Fernet 加密

    # sse / streamable_http
    url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    headers_encrypted: Mapped[str] = mapped_column(Text, default="")  # Fernet 加密

    # 运行时
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_reconnect: Mapped[bool] = mapped_column(Boolean, default=True)
    timeout: Mapped[int] = mapped_column(Integer, default=30)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    allowed_users: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    require_approval: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    @classmethod
    def from_config(cls, cfg: McpServerConfig) -> "McpServerRecord":
        """McpServerConfig -> ORM(env/headers 加密落库)。"""
        return cls(
            id=cfg.id,
            name=cfg.name,
            description=cfg.description,
            transport=cfg.transport,
            command=cfg.command,
            args=cfg.args or [],
            env_encrypted=encrypt_dict(cfg.env),
            url=cfg.url,
            headers_encrypted=encrypt_dict(cfg.headers),
            enabled=cfg.enabled,
            auto_reconnect=cfg.auto_reconnect,
            timeout=cfg.timeout,
            max_retries=cfg.max_retries,
            allowed_users=cfg.allowed_users,
            require_approval=cfg.require_approval,
        )

    def to_config(self) -> McpServerConfig:
        """ORM -> McpServerConfig(env/headers 解密)。"""
        return McpServerConfig(
            id=self.id,
            name=self.name or "",
            description=self.description or "",
            transport=self.transport or "stdio",
            command=self.command,
            args=self.args or [],
            env=decrypt_dict(self.env_encrypted),
            url=self.url,
            headers=decrypt_dict(self.headers_encrypted),
            enabled=self.enabled,
            auto_reconnect=self.auto_reconnect,
            timeout=self.timeout,
            max_retries=self.max_retries,
            allowed_users=self.allowed_users,
            require_approval=self.require_approval,
        )
