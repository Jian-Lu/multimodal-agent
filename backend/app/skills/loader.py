"""Skill System — SkillLoader (扫描内置 YAML)。

所属层级: Tool/Registry
"""
from pathlib import Path

import yaml

from app.skills.schema import Skill


class SkillLoader:
    """从目录加载内置技能 YAML。"""

    @staticmethod
    def load_builtin(directory: str | Path) -> list[Skill]:
        """扫描目录下 *.yaml, 解析为 Skill 列表。"""
        dir_path = Path(directory)
        if not dir_path.is_dir():
            return []
        skills: list[Skill] = []
        for f in sorted(dir_path.glob("*.yaml")):
            data = yaml.safe_load(f.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "name" in data:
                skills.append(Skill(**data))
        return skills
