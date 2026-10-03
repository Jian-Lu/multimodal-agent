"""Skill System — Skill Pydantic 模型。

所属层级: Tool/Registry
"""
from pydantic import BaseModel, Field


class Skill(BaseModel):
    """可插拔技能定义(自描述)。"""

    name: str
    description: str = ""
    triggers: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    system_prompt_template: str = ""
    config_schema: dict = Field(default_factory=dict)
    target_agent: str = "rag"   # 命中后路由到的 agent
    enabled: bool = True
    builtin: bool = False
