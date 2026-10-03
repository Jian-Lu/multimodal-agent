"""Tool/Registry 层 — Skill System 单元测试。"""
from langchain_core.messages import HumanMessage

from app.harness.supervisor import supervisor_node
from app.skills import BUILTIN_DIR
from app.skills.loader import SkillLoader
from app.skills.registry import SkillRegistry
from app.skills.schema import Skill


def test_skill_schema():
    s = Skill(name="test", description="d")
    assert s.name == "test"
    assert s.triggers == []
    assert s.target_agent == "rag"
    assert s.enabled is True
    assert s.builtin is False


def test_registry_match():
    reg = SkillRegistry()
    reg.register(Skill(name="s1", triggers=["数据分析", "图表"]))
    reg.register(Skill(name="s2", triggers=["总结"]))
    assert reg.match("帮我做数据分析").name == "s1"
    assert reg.match("帮我总结文档").name == "s2"
    assert reg.match("你好") is None


def test_registry_enable_disable():
    reg = SkillRegistry()
    reg.register(Skill(name="s1", triggers=["数据分析"]))
    assert reg.match("数据分析") is not None
    reg.set_enabled("s1", False)
    assert reg.match("数据分析") is None
    reg.set_enabled("s1", True)
    assert reg.match("数据分析") is not None


def test_loader_loads_builtin():
    skills = SkillLoader.load_builtin(BUILTIN_DIR)
    names = {s.name for s in skills}
    assert "data_analysis" in names
    assert "document_summarize" in names


def test_render_prompt():
    reg = SkillRegistry()
    skill = Skill(
        name="s",
        system_prompt_template="语言: {{ language }}",
        config_schema={"language": {"type": "string", "default": "中文"}},
    )
    assert reg.render_prompt(skill, {}) == "语言: 中文"
    assert reg.render_prompt(skill, {"language": "英文"}) == "语言: 英文"


def test_supervisor_skill_routing():
    from app.skills import load_builtin_skills

    load_builtin_skills()
    r = supervisor_node({"messages": [HumanMessage(content="帮我做数据分析")]})
    assert r["next_agent"] == "coder"
    assert r["skill"] == "data_analysis"
