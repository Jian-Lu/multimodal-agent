"""Skill System — SkillRegistry。

所属层级: Tool/Registry
"""
from jinja2 import Template

from app.skills.schema import Skill


class SkillRegistry:
    """技能注册表(内存)。"""

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        self._skills[skill.name] = skill

    def unregister(self, name: str) -> None:
        self._skills.pop(name, None)

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def list(self, enabled_only: bool = False) -> list[Skill]:
        skills = list(self._skills.values())
        if enabled_only:
            skills = [s for s in skills if s.enabled]
        return sorted(skills, key=lambda s: s.name)

    def set_enabled(self, name: str, enabled: bool) -> bool:
        skill = self._skills.get(name)
        if skill is None:
            return False
        skill.enabled = enabled
        return True

    def match(self, text: str) -> Skill | None:
        """按 triggers 子串匹配, 返回第一个命中的已启用技能。"""
        t = (text or "").lower()
        for skill in sorted(self._skills.values(), key=lambda s: s.name):
            if not skill.enabled:
                continue
            if any(trig.lower() in t for trig in skill.triggers):
                return skill
        return None

    def render_prompt(self, skill: Skill, context: dict | None = None) -> str:
        """Jinja2 渲染 system_prompt_template(config_schema 默认值兜底变量)。"""
        ctx = dict(context or {})
        for key, spec in (skill.config_schema or {}).items():
            if key not in ctx and isinstance(spec, dict) and "default" in spec:
                ctx[key] = spec["default"]
        try:
            return Template(skill.system_prompt_template).render(**ctx)
        except Exception:  # noqa: BLE001 — 模板异常时返回原文
            return skill.system_prompt_template


# 全局单例
_registry = SkillRegistry()


def get_skill_registry() -> SkillRegistry:
    """获取全局 SkillRegistry 单例。"""
    return _registry
