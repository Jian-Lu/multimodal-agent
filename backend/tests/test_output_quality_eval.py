"""Evaluation 层 — Layer 3 输出质量评估 单元测试 (全部离线桩, 零 LLM/网络/真实 Agent)。

所属层级: Evaluation / Layer 3
"""
import asyncio
import json
import time

import pytest
from langchain_core.messages import AIMessage

from app.evaluation import llm_judge
from app.evaluation.test_output_quality import (
    AGENT_JUDGE,
    DEFAULT_GOLDEN,
    QualityCase,
    agent_scores,
    load_output_golden,
    run_quality_eval,
)
from app.evaluation.llm_judge import (
    KIND_CRITERIA,
    VERDICT_MODELS,
    WritingVerdict,
    build_prompt,
    llm_judge_one,
    normalize_verdict,
    parse_judge_json,
)

AGENTS = {"coder", "writer", "web_search"}
JUDGES = {"code", "writing", "search"}


def run(coro):
    return asyncio.run(coro)


# ---------- golden 数据集 schema ----------

def test_golden_loads_and_schema():
    cases = load_output_golden(DEFAULT_GOLDEN)
    assert len(cases) >= 10
    ids = {c.id for c in cases}
    assert len(ids) == len(cases)  # id 唯一
    assert {c.agent for c in cases} == AGENTS
    assert {c.judge for c in cases} == JUDGES
    for c in cases:
        assert c.input.strip()
        assert c.reference.strip()
        assert c.judge == AGENT_JUDGE[c.agent]


def test_judge_taxonomy_consistent():
    # golden 的 judge 集合与判分维度/结构化模型一一对应
    assert set(KIND_CRITERIA) == JUDGES
    assert set(VERDICT_MODELS) == JUDGES
    for kind, criteria in KIND_CRITERIA.items():
        assert len(criteria) >= 2
        assert len(criteria) == len(set(criteria))


# ---------- prompt / 解析 / 归一化 ----------

def test_build_prompt_contains_blocks():
    p = build_prompt("code", "问题AAA", "输出BBB", "参考CCC")
    assert "问题AAA" in p and "输出BBB" in p and "参考CCC" in p
    assert "executability" in p
    with pytest.raises(ValueError):
        build_prompt("unknown_kind", "q", "o")


def test_parse_judge_json_variants():
    # 带 ```json 围栏
    text = '```json\n{"executability": 4, "correctness": 5}\n```'
    assert parse_judge_json(text, KIND_CRITERIA["code"]) == {
        "executability": 4, "correctness": 5,
    }
    # 带前后缀噪音
    raw = '打分如下: {"structure": "4", "comment": "ok"} 结束'
    data = parse_judge_json(raw, KIND_CRITERIA["writing"])
    assert data["structure"] == "4"
    assert data["comment"] == "ok"
    # 非 JSON -> None
    assert parse_judge_json("完全不是json", KIND_CRITERIA["code"]) is None
    assert parse_judge_json("", KIND_CRITERIA["code"]) is None


def test_normalize_verdict_math_and_clamp():
    v = WritingVerdict(structure=5, information_density=4, readability=3, comment="还行")
    n = normalize_verdict("writing", v)
    assert n["criteria"] == {"structure": 5.0, "information_density": 4.0, "readability": 3.0}
    assert n["overall"] == pytest.approx(4.0)
    assert n["comment"] == "还行"

    # 越界钳制 + 未知键忽略 + 缺失维度不计入
    d = {"executability": 9, "correctness": 0, "robustness": "4", "evil": 1}
    n2 = normalize_verdict("code", d)
    assert n2["criteria"]["executability"] == 5.0
    assert n2["criteria"]["correctness"] == 1.0
    assert "code_quality" not in n2["criteria"]  # 缺 code_quality -> 跳过
    assert n2["criteria"]["robustness"] == 4.0
    assert n2["overall"] == pytest.approx((5 + 1 + 4) / 3, abs=0.01)  # normalize 四舍五入到 2 位

    # 维度全缺 -> None
    assert normalize_verdict("code", {"comment": "no numbers"}) is None


# ---------- llm_judge_one (注入 fake, 零网络) ----------

class _StructuredHappy:
    def __init__(self, verdict):
        self.verdict = verdict
        self.schema = None

    def with_structured_output(self, schema):
        self.schema = schema
        return self

    async def ainvoke(self, prompt):
        assert self.schema is WritingVerdict
        return self.verdict


def test_llm_judge_one_structured_happy():
    fake = _StructuredHappy(WritingVerdict(structure=5, information_density=4, readability=3, comment="ok"))
    result = run(llm_judge_one("writing", "问题", "候选", llm=fake))
    assert result["overall"] == pytest.approx(4.0)
    assert result["criteria"] == {"structure": 5.0, "information_density": 4.0, "readability": 3.0}
    assert result["comment"] == "ok"


class _StructuredRaises:
    async def ainvoke(self, prompt):
        raise RuntimeError("tool calling 不支持")


class _FallbackLLM:
    def with_structured_output(self, schema):
        return _StructuredRaises()

    async def ainvoke(self, prompt):
        text = json.dumps(
            {"executability": 5, "correctness": 5, "code_quality": 4,
             "robustness": 2, "comment": "works"}, ensure_ascii=False,
        )
        return AIMessage(content=text)


def test_llm_judge_one_structured_error_falls_back_to_parse():
    result = run(llm_judge_one("code", "问题", "候选", llm=_FallbackLLM()))
    assert result["overall"] == pytest.approx((5 + 5 + 4 + 2) / 4)
    assert result["criteria"]["robustness"] == 2.0
    assert result["comment"] == "works"


def test_llm_judge_one_unparseable_returns_none():
    fake = _StructuredHappy(None)  # 结构化返回 None -> normalize(None) -> None? 见下方直接用例
    assert run(llm_judge_one("code", "q", "o", llm=fake)) is None


class _SlowLLM:
    def with_structured_output(self, schema):
        class _Slow:
            async def ainvoke(self, prompt):
                await asyncio.sleep(30)
                raise AssertionError("不应到达")
        return _Slow()


def test_llm_judge_one_timeout_returns_none_quickly():
    t0 = time.monotonic()
    result = run(llm_judge_one("code", "q", "o", llm=_SlowLLM(), timeout=0.05))
    elapsed = time.monotonic() - t0
    assert result is None
    assert elapsed < 1.0  # 超时被 asyncio.wait_for 掐断, 未等满 30s


# ---------- 聚合 ----------

def _row(i, agent, overall, crit):
    return {"id": i, "agent": agent, "judge": AGENT_JUDGE[agent], "overall": overall,
            "criteria": crit, "comment": ""}


def test_agent_scores_math():
    rows = [
        _row("a1", "coder", 4.0, {"executability": 5, "correctness": 4, "code_quality": 4, "robustness": 3}),
        _row("a2", "coder", 2.0, {"executability": 2, "correctness": 2, "code_quality": 3, "robustness": 1}),
        _row("w1", "writer", 5.0, {"structure": 5, "information_density": 5, "readability": 5}),
    ]
    s = agent_scores(rows)
    coder = s["coder"]
    assert coder["n"] == 2
    assert coder["overall_avg"] == pytest.approx(3.0)
    assert coder["min_overall"] == 2.0
    assert coder["min_case"] == {"id": "a2", "overall": 2.0}
    assert coder["criteria_avg"]["executability"] == pytest.approx(3.5)
    assert s["writer"]["overall_avg"] == 5.0


# ---------- run_quality_eval dry (零 LLM/网络/真实 Agent) ----------

def test_dry_full_golden_self_consistent_full_marks():
    cases = load_output_golden(DEFAULT_GOLDEN)
    result = run(run_quality_eval(cases, mode="dry"))
    assert result["layer"] == "quality"
    assert result["mode"] == "dry"
    assert result["judged_by"] == "stub"
    assert result["total"] == len(cases)
    assert result["scored"] == len(cases)
    assert result["errors"] == []
    assert result["failures"] == []

    assert set(result["agents"]) == AGENTS
    for agent, st in result["agents"].items():
        assert st["judge"] == AGENT_JUDGE[agent]
        assert st["overall_avg"] == 5.0
        assert all(v == 5.0 for v in st["criteria_avg"].values())
    # 可 JSON 序列化 (供端点/报告消费)
    json.dumps(result, ensure_ascii=False)


class _PassFailJudge:
    """question 含 'FAIL' 时拒判(None), 否则给整体 2.0 低分(触发 failures)。"""

    async def __call__(self, kind, question, output, reference=None):
        if "FAIL" in question:
            return None
        crit = {c: 2.0 for c in KIND_CRITERIA.get(kind, [])}
        return {"criteria": crit, "overall": 2.0, "comment": "fake low"}


def test_failures_and_errors_capture_with_inject_judge():
    cases = [
        QualityCase(id="c1", agent="coder", judge="code", input="写个排序", reference="排序代码"),
        QualityCase(id="w1", agent="writer", judge="writing", input="写份报告 FAIL 场景", reference="报告"),
    ]
    result = run(run_quality_eval(cases, mode="dry", judge=_PassFailJudge(), fail_below=3.0))

    assert result["scored"] == 1  # c1 得分
    assert [e["id"] for e in result["errors"]] == ["w1"]  # FAIL -> judge_no_verdict
    assert [f["id"] for f in result["failures"]] == ["c1"]  # overall 2.0 < 3.0
    assert result["agents"]["coder"]["min_overall"] == 2.0
    assert result["agents"]["coder"]["min_case"]["id"] == "c1"
    assert "output_excerpt" in result["failures"][0]
