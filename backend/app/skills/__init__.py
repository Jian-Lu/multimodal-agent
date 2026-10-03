"""Skill System — 公共接口 + 启动装配。

所属层级: Tool/Registry
"""
from pathlib import Path

from sqlalchemy import select

from app.skills.loader import SkillLoader
from app.skills.registry import SkillRegistry, get_skill_registry
from app.skills.schema import Skill

BUILTIN_DIR = Path(__file__).parent / "builtin"

__all__ = ["Skill", "SkillRegistry", "get_skill_registry", "load_builtin_skills"]


def load_builtin_skills() -> list[Skill]:
    """加载内置技能并注册到全局 registry(标记 builtin)。"""
    registry = get_skill_registry()
    skills = SkillLoader.load_builtin(BUILTIN_DIR)
    for s in skills:
        s.builtin = True
        registry.register(s)
    return skills


async def load_custom_skills(db) -> None:
    """从数据库加载自定义技能并注册到全局 registry。"""
    from app.models import SkillRecord

    result = await db.scalars(select(SkillRecord))
    registry = get_skill_registry()
    for record in result.all():
        registry.register(record.to_skill())
