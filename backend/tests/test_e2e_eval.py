"""Evaluation 层 — Layer 4 E2E 场景评估 单元测试 (全部离线桩, 零 LLM/网络/真实 graph)。

所属层级: Evaluation / Layer 4
"""
import asyncio
import json

import pytest

from app.evaluation.test_e2e import (
    CHECK_TYPES,
    DEFAULT_SCENARIOS,
    E2ECase,
    check_format,
    check_mcp_tool,
    check_multi_agent,
    check_output_pattern,
    check_routing,
    dry_trace,
    evaluate_checks,
    load_e2e_scenarios,
    run_e2e_eval,
)


def run(coro):
    return asyncio.run(coro)


def _trace(**kw) -> dict:
    base = {"nodes": [], "tools": [], "final_answer": "", "route": "finish", "error": None}
    base.update(kw)
    return base


# ---------- scenario 数据集 ----------

def test_dataset_lint_and_coverage():
    cases = load_e2e_scenarios(DEFAULT_SCENARIOS)
    assert len(cases) >= 10
    ids = {c.id for c in cases}
    assert len(ids) == len(cases)
    seen_types: set[str] = set()
    for c in cases:
        assert c.name and c.category and c.input.strip()
        assert c.mode in ("chat", "document")
        assert c.checks, f"{c.id} 无 check"
        for spec in c.checks:
            assert spec["type"] in CHECK_TYPES
            seen_types.add(spec["type"])
    assert seen_types == CHECK_TYPES  # 5 种 check 全覆盖


def test_loader_rejects_bad_input(tmp_path):
    good = [{"id": "x", "name": "n", "category": "c", "mode": "chat", "input": "i",
             "checks": [{"type": "routing_check", "expected": "coder"}]}]
    bad = dict(good[0])
    bad["checks"] = [{"type": "bogus"}]
    p = tmp_path / "s.json"
    p.write_text(json.dumps([bad]), encoding="utf-8")
    with pytest.raises(ValueError, match="未知 check type"):
        load_e2e_scenarios(p)

    bad2 = dict(good[0])
    bad2["checks"] = [{"type": "format_check", "min_length": 1}]
    p.write_text(json.dumps([good[0], {**good[0], "id": "x"}] + [dict(bad2)]), encoding="utf-8")
    with pytest.raises(ValueError, match="id 重复"):
        load_e2e_scenarios(p)


# ---------- 5 个判定函数 正/反例 ----------

def test_check_routing():
    tr = _trace(route="coder")
    assert check_routing(tr, {"type": "routing_check", "expected": "coder"})["ok"]
    assert not check_routing(tr, {"type": "routing_check", "expected": "writer"})["ok"]
    assert check_routing(_trace(route="finish"), {"expected": "finish"})["ok"]


def test_check_multi_agent():
    tr = _trace(nodes=["coder", "sandbox"])
    assert check_multi_agent(tr, {"agents": ["coder", "sandbox"]})["ok"]
    assert not check_multi_agent(tr, {"agents": ["sandbox", "coder"]})["ok"]  # 乱序
    assert not check_multi_agent(tr, {"agents": ["coder", "writer"]})["ok"]   # 缺 agent
    # 允许夹其他节点 (子序列)
    assert check_multi_agent(_trace(nodes=["web_search", "supervisor", "writer"]),
                             {"agents": ["web_search", "writer"]})["ok"]


def test_check_output_pattern():
    tr = _trace(final_answer="先看\n```python\nprint(1)\n```\n结束")
    assert check_output_pattern(tr, {"pattern": "```python"})["ok"]
    assert not check_output_pattern(tr, {"pattern": "mermaid"})["ok"]


def test_check_mcp_tool():
    tr = _trace(tools=["mcp_github_get_issues", "mcp_github_get_repository"])
    assert check_mcp_tool(tr, {"tool": "mcp_github_"})["ok"]
    assert check_mcp_tool(tr, {"tool": "mcp_github_get_issues"})["ok"]
    assert not check_mcp_tool(_trace(tools=["python_repl"]), {"tool": "mcp_github_"})["ok"]
    assert not check_mcp_tool(_trace(tools=[]), {"tool": "mcp_github_"})["ok"]


def test_check_format():
    good = _trace(final_answer="A" * 100)
    assert check_format(good, {"min_length": 80})["ok"]
    assert not check_format(good, {"min_length": 200})["ok"]
    assert not check_format(_trace(final_answer="出现 Traceback 了"),
                            {"must_not": ["Traceback", "搜索服务暂时不可用"]})["ok"]
    assert check_format(_trace(final_answer="没问题"), {"must_not": ["Traceback"]})["ok"]


# ---------- evaluate_checks / unknown / dry 自洽 ----------

def test_evaluate_checks_unknown_and_aggregation():
    tr = _trace(route="coder", nodes=["coder", "sandbox"], final_answer="A" * 50)
    checks = (
        {"type": "routing_check", "expected": "coder"},
        {"type": "multi_agent_check", "agents": ["coder", "sandbox"]},
        {"type": "format_check", "min_length": 100},  # 会失败
        {"type": "not_a_check"},
    )
    v = evaluate_checks(tr, checks)
    assert not v["all_ok"]
    by_type = {r["type"]: r for r in v["checks"]}
    assert by_type["routing_check"]["ok"]
    assert by_type["multi_agent_check"]["ok"]
    assert not by_type["format_check"]["ok"]
    assert not by_type["not_a_check"]["ok"]
    assert "unknown_check:not_a_check" in by_type["not_a_check"]["detail"]


def test_dry_full_dataset_self_consistent():
    cases = load_e2e_scenarios(DEFAULT_SCENARIOS)
    result = run(run_e2e_eval(cases, mode="dry"))
    assert result["layer"] == "e2e"
    assert result["mode"] == "dry"
    assert result["total"] == len(cases)
    assert result["passed"] == result["total"]
    assert result["pass_rate"] == 1.0
    assert result["failures"] == []
    # by_check: 每种出现次数 = 通过次数
    assert set(result["by_check"]) == CHECK_TYPES
    for st in result["by_check"].values():
        assert st["passed"] == st["n"]
    # by_category 覆盖所有 category 且全过
    assert set(result["by_category"]) == {c.category for c in cases}
    assert all(st["passed"] == st["n"] for st in result["by_category"].values())
    # scenarios 与数据集一一对应
    assert [s["id"] for s in result["scenarios"]] == [c.id for c in cases]
    json.dumps(result, ensure_ascii=False)


def test_error_trace_counts_as_failure():
    cases = [
        E2ECase(id="ok1", name="过", category="coding", mode="chat", input="i",
                checks=({"type": "routing_check", "expected": "coder"},)),
        E2ECase(id="err1", name="依赖缺", category="rag_mcp", mode="chat", input="i",
                checks=({"type": "mcp_tool_check", "tool": "mcp_github_"},)),
    ]

    async def producer(case):
        if case.id == "err1":
            return _trace(error="ConnectionError: GitHub MCP 未连接")
        return dry_trace(case)

    result = run(run_e2e_eval(cases, mode="dry", producer=producer))
    assert result["passed"] == 1
    assert result["total"] == 2
    assert [f["id"] for f in result["failures"]] == ["err1"]
    assert "ConnectionError" in result["failures"][0]["error"]
    assert "trace_error" in result["failures"][0]["reason"]
    # 出错的 scenario 不计入 by_check (无已执行 check)
    assert "mcp_tool_check" not in result["by_check"] or result["by_check"]["mcp_tool_check"]["n"] == 0


def test_dry_trace_satisfies_declared_checks():
    case = E2ECase(id="t", name="冒烟", category="coding", mode="chat", input="i",
                   checks=(
                       {"type": "routing_check", "expected": "coder"},
                       {"type": "multi_agent_check", "agents": ["coder", "sandbox"]},
                       {"type": "output_pattern", "pattern": "```python"},
                       {"type": "format_check", "min_length": 80},
                   ))
    tr = dry_trace(case)
    assert tr["route"] == "coder"
    assert tr["nodes"] == ["coder", "sandbox"]
    assert len(tr["final_answer"]) >= 80
    assert evaluate_checks(tr, case.checks)["all_ok"]
