"""Evaluation 层 — Layer 2 路由准确性评估 单元测试 (全部离线桩, 零 LLM/网络)。

所属层级: Evaluation / Layer 2
"""
import asyncio
import json

import pytest

from app.evaluation.test_routing import (
    DEFAULT_GOLDEN,
    RoutingCase,
    compute_routing_metrics,
    load_golden,
    run_routing_eval,
)

EXPECTED_CATEGORIES = {
    "coder", "web_search", "mcp_github", "skill", "rag", "writer", "vision", "finish",
}


def run(coro):
    return asyncio.run(coro)


# ---------- 纯指标数学 ----------

def test_metrics_math():
    expected = ["coder", "coder", "rag", "web_search", "coder"]
    predicted = ["coder", "coder", "web_search", "web_search", "coder"]
    m = compute_routing_metrics(expected, predicted, categories=expected)

    assert m["total"] == 5
    assert m["correct"] == 4
    assert m["accuracy"] == pytest.approx(0.8)

    c = m["per_label"]["coder"]
    assert (c["precision"], c["recall"], c["f1"], c["support"]) == (1.0, 1.0, 1.0, 3)
    rag = m["per_label"]["rag"]
    assert (rag["precision"], rag["recall"], rag["f1"], rag["support"]) == (0.0, 0.0, 0.0, 1)
    ws = m["per_label"]["web_search"]
    assert ws["precision"] == pytest.approx(0.5)
    assert ws["recall"] == 1.0
    assert ws["f1"] == pytest.approx(0.6667, abs=1e-3)

    # macro: 仅 support>0 标签 (coder/rag/web_search) 均值
    assert m["macro_f1"] == pytest.approx((1.0 + 0.0 + 0.6667) / 3, abs=1e-3)

    cm = m["confusion_matrix"]
    assert cm["rag"]["web_search"] == 1
    assert cm["coder"]["coder"] == 3


def test_confusion_matrix_shape():
    expected = ["a", "b", "a"]
    predicted = ["a", "a", "c"]
    labels = ["a", "b", "c"]
    mat = {
        actual: {pred: 0 for pred in labels} for actual in labels
    }
    for e, p in zip(expected, predicted):
        mat[e][p] += 1
    assert mat == {"a": {"a": 1, "b": 0, "c": 1},
                   "b": {"a": 1, "b": 0, "c": 0},
                   "c": {"a": 0, "b": 0, "c": 0}}


def test_by_category_accuracy():
    expected = ["coder", "coder", "rag"]
    predicted = ["coder", "coder", "web_search"]
    m = compute_routing_metrics(expected, predicted, categories=["coder", "coder", "rag"])
    assert m["by_category"]["coder"]["accuracy"] == 1.0
    assert m["by_category"]["rag"]["accuracy"] == 0.0


# ---------- golden 数据集 schema ----------

def test_golden_loads_and_schema():
    cases = load_golden(DEFAULT_GOLDEN)
    assert len(cases) >= 30
    cats = {c.category for c in cases}
    assert cats == EXPECTED_CATEGORIES
    seen = {c.id for c in cases}
    assert len(seen) == len(cases)  # id 唯一
    for c in cases:
        assert c.input
        assert c.expected_agent in EXPECTED_CATEGORIES | {"coder", "web_search",
                                                          "mcp_github", "rag", "writer",
                                                          "vision", "finish"}
        assert c.category in EXPECTED_CATEGORIES
        # skill 类必须有 expected_skill; 其他类必须为 None
        if c.category == "skill":
            assert c.expected_skill in ("data_analysis", "document_summarize")
        else:
            assert c.expected_skill is None


def test_golden_rule_overrides_present():
    cases = {c.id: c for c in load_golden(DEFAULT_GOLDEN)}
    assert cases["r025"].mode == "document"          # writer 规则覆盖
    assert cases["r026"].images is True              # vision 规则覆盖
    assert cases["r029"].iteration == 10             # finish 规则覆盖


# ---------- dry 桩端到端 (走真实 supervisor_node, 但零 LLM) ----------

def test_dry_rule_branch_vision():
    case = next(c for c in load_golden(DEFAULT_GOLDEN) if c.id == "r026")
    result = run(run_routing_eval([case], mode="dry"))
    assert result["total"] == 1
    assert result["correct"] == 1
    assert result["accuracy"] == 1.0
    assert result["failures"] == []


def test_dry_full_golden_shape_and_rule_skill_ids():
    cases = load_golden(DEFAULT_GOLDEN)
    result = run(run_routing_eval(cases, mode="dry"))
    assert result["layer"] == "routing"
    assert result["mode"] == "dry"
    assert result["total"] == len(cases)
    assert len(result["failures"]) == result["total_failures"]

    fail_ids = {f["id"] for f in result["failures"]}
    # 规则分支 (r025/r026/r027/r029) 与 skill 分支 (r030-r034) dry 下必须命中
    for rule_id in ("r025", "r026", "r027", "r029"):
        assert rule_id not in fail_ids, f"规则分支 {rule_id} dry 应命中"
    for skill_id in ("r030", "r031", "r032", "r033", "r034"):
        assert skill_id not in fail_ids, f"skill 分支 {skill_id} dry 应命中"

    # 结果可 JSON 序列化 (供端点/报告消费)
    json.dumps(result, ensure_ascii=False)
    # by_category 覆盖全部分类
    assert set(result["by_category"]) == EXPECTED_CATEGORIES
