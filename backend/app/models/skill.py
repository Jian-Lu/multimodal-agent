"""SkillRecord 模型 — 自定义技能(数据库存储)。

所属层级: DB / 数据模型
"""
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SkillRecord(Base):
    __tablename__ = "skills"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    description: Mapped[str] = mapped_column(String(512), default="")
    triggers: Mapped[list] = mapped_column(JSON, default=list)
    tools: Mapped[list] = mapped_column(JSON, default=list)
    system_prompt_template: Mapped[str] = mapped_column(Text, default="")
    config_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    target_agent: Mapped[str] = mapped_column(String(32), default="rag")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def to_skill(self):
        """转为 Skill(Pydantic) 模型。"""
        from app.skills.schema import Skill

        return Skill(
            name=self.name,
            description=self.description or "",
            triggers=self.triggers or [],
            tools=self.tools or [],
            system_prompt_template=self.system_prompt_template or "",
            config_schema=self.config_schema or {},
            target_agent=self.target_agent or "rag",
            enabled=self.enabled,
            builtin=False,
        )
