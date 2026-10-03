"""Evaluation 层 — Layer 2 路由准确性评估 (test_routing).

所属层级: Evaluation / Layer 2

判定口径 = 语义决策层: 用 spy 捕获 supervisor 调用 real Routing LLM 后解析出的
RoutingDecision (含 mcp_github / skill_name), 不改 supervisor 业务代码。
supervisor 内部的折叠 (mcp_github→rag, skill→target_agent) 发生在评测之后,
因此 mcp_github / skill 分支可被独立统计。

模式:
  live —— 委托真实 get_llm_by_intent(...).with_structured_output(RoutingDecision);
  dry  —— _rule_decision 关键字桩 (零 LLM / 零网络)。

用法:
  python -m app.evaluation.test_routing --mode dry [--json]
"""
import argparse
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from langchain_core.messages import HumanMessage

from app.harness import supervisor as sup

logger = logging.getLogger("evaluation.routing")

DEFAULT_GOLDEN = Path(__file__).resolve().parent / "golden_datasets" / "routing_golden.json"

# 1px 透明 PNG (仅用于触发 supervisor 的 images→vision 规则分支, 不做真实视觉推理)
STUB_IMAGE = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


# ---------- golden 数据集 ----------
@dataclass
class RoutingCase:
    id: str
    input: str
    expected_agent: str
    expected_skill: Optional[str]
    category: str
    mode: str = "chat"
    images: bool = False
    iteration: Optional[int] = None

    @property
    def expected_label(self) -> str:
        """单标签口径: 期望 skill 优先, 否则期望 agent。"""
        return self.expected_skill or self.expected_agent


def load_golden(path: str | Path = DEFAULT_GOLDEN) -> list[RoutingCase]:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    cases = []
    for item in raw:
        cases.append(
            RoutingCase(
                id=item["id"],
                input=item["input"],
                expected_agent=item["expected_agent"],
                expected_skill=item.get("expected_skill"),
                category=item["category"],
                mode=item.get("mode", "chat"),
                images=bool(item.get("images", False)),
                iteration=item.get("iteration"),
            )
        )
    return cases


# ---------- 纯指标函数 ----------
def _div(num: float, den: float) -> float:
    return round(num / den, 4) if den else 0.0


def label_metrics(expected: list[str], predicted: list[str]) -> tuple[list[str], dict[str, dict]]:
    """每标签 tp/fp/fn/precision/recall/f1/support。"""
    labels: list[str] = []
    for label in expected + predicted:
        if label not in labels:
            labels.append(label)
    per_label: dict[str, dict] = {}
    for label in labels:
        tp = sum(1 for e, p in zip(expected, predicted) if e == label and p == label)
        fp = sum(1 for e, p in zip(expected, predicted) if e != label and p == label)
        fn = sum(1 for e, p in zip(expected, predicted) if e == label and p != label)
        precision = _div(tp, tp + fp)
        recall = _div(tp, tp + fn)
        f1 = _div(2 * precision * recall, precision + recall)
        per_label[label] = {
            "tp": tp, "fp": fp, "fn": fn,
            "precision": precision, "recall": recall, "f1": f1,
            "support": tp + fn,
        }
    return labels, per_label


def macro_f1(per_label: dict[str, dict]) -> float:
    """仅对 ground-truth 中出现过的标签 (support>0) 求宏平均 F1。"""
    scores = [m["f1"] for m in per_label.values() if m["support"] > 0]
    return round(sum(scores) / len(scores), 4) if scores else 0.0


def confusion_matrix(expected: list[str], predicted: list[str], labels: list[str]) -> dict[str, dict]:
    """混淆矩阵: matrix[实际(expected)][预测(predicted)] = count。"""
    mat = {actual: {pred: 0 for pred in labels} for actual in labels}
    for e, p in zip(expected, predicted):
        if e in mat and p in mat[e]:
            mat[e][p] += 1
    return mat


def by_category_accuracy(expected: list[str], predicted: list[str], categories: list[str]) -> dict:
    agg: dict[str, dict] = {}
    for e, p, cat in zip(expected, predicted, categories):
        bucket = agg.setdefault(cat, {"total": 0, "correct": 0})
        bucket["total"] += 1
        if e == p:
            bucket["correct"] += 1
    return {
        cat: {"total": v["total"], "correct": v["correct"], "accuracy": _div(v["correct"], v["total"])}
        for cat, v in agg.items()
    }


def compute_routing_metrics(expected: list[str], predicted: list[str], categories: list[str]) -> dict:
    """汇总 accuracy / 每标签指标 / macro F1 / 混淆矩阵 / 按类别正确率。"""
    total = len(expected)
    correct = sum(1 for e, p in zip(expected, predicted) if e == p)
    labels, per_label = label_metrics(expected, predicted)
    return {
        "total": total,
        "correct": correct,
        "accuracy": _div(correct, total),
        "labels": labels,
        "per_label": per_label,
        "macro_f1": macro_f1(per_label),
        "confusion_matrix": confusion_matrix(expected, predicted, labels),
        "by_category": by_category_accuracy(expected, predicted, categories),
    }


# ---------- dry 桩决策 (关键字规则, 不读取 golden expected) ----------
_FINISH_TOKENS = ("谢谢", "没有其他问题", "再见", "结束对话", "不用了")
_GITHUB_TOKENS = ("github", "issue", "issues", "pull request", "仓库的 star", "star 数",
                  "仓库提", "open 状态的 pr", "贡献者列表", " 的 pr")
_SEARCH_TOKENS = ("搜索", "搜一下", "查一下", "最新", "新闻", "资讯", "天气", "排名", "发布了", "趋势", "大新闻")
_SKILL_DA_TOKENS = ("数据分析", "做数据分析", "统计分析", "画图表", "趋势图", "pandas", "csv 数据")
_SKILL_DS_TOKENS = ("总结文档", "文档总结", "提炼要点", "结构化总结", "帮我总结")
_CODER_TOKENS = ("python", "javascript", "脚本", "函数", "修复", "bug", "实现", "代码", "算法",
                 "sql", "防抖", "lru", "class", "排序")
_WRITER_TOKENS = ("报告", "markdown 文档", "纪要", "复盘", "整理", "生成一份", "书面")


def _rule_decision(text: str) -> sup.RoutingDecision:
    """确定性关键字路由 (dry 桩), 模拟高层意图; 网络/模型为零。"""
    t = (text or "").lower()
    if any(k in t for k in _FINISH_TOKENS):
        return sup.RoutingDecision(next_agent="finish", reasoning="dry-finish", confidence=0.9)
    if any(k in t for k in _SKILL_DA_TOKENS):
        return sup.RoutingDecision(next_agent="coder", skill_name="data_analysis",
                                   reasoning="dry-skill-da", confidence=0.9)
    if any(k in t for k in _SKILL_DS_TOKENS):
        return sup.RoutingDecision(next_agent="rag", skill_name="document_summarize",
                                   reasoning="dry-skill-ds", confidence=0.9)
    if any(k in t for k in _GITHUB_TOKENS):
        return sup.RoutingDecision(next_agent="mcp_github", reasoning="dry-github", confidence=0.9)
    if any(k in t for k in _SEARCH_TOKENS):
        return sup.RoutingDecision(next_agent="web_search", reasoning="dry-search", confidence=0.9)
    if any(k in t for k in _CODER_TOKENS):
        return sup.RoutingDecision(next_agent="coder", reasoning="dry-code", confidence=0.9)
    if any(k in t for k in _WRITER_TOKENS):
        return sup.RoutingDecision(next_agent="writer", reasoning="dry-writer", confidence=0.9)
    return sup.RoutingDecision(next_agent="rag", reasoning="dry-default", confidence=0.9)


def _extract_text(messages: list[Any]) -> str:
    last = messages[-1] if messages else None
    if last is None:
        return ""
    content = getattr(last, "content", last)
    return content if isinstance(content, str) else ""


# ---------- routing LLM spy ----------
class _Structured:
    """替身: 提供 supervisor 期望的 .ainvoke()。"""

    def __init__(self, invoke) -> None:
        self._invoke = invoke

    async def ainvoke(self, messages, **kwargs):
        return await self._invoke(messages)


class _FakeRouted:
    """替身 RoutedLLM: 只实现 with_structured_output。"""

    def __init__(self, structured: _Structured) -> None:
        self._structured = structured

    def with_structured_output(self, schema):
        return self._structured


@asynccontextmanager
async def routing_spy(mode: str, captured: dict[str, sup.RoutingDecision]):
    """monkeypatch supervisor.get_llm_by_intent, 捕获每次语义决策。

    captured: {HumanMessage 文本 -> RoutingDecision}。
    live 委托真实模型链 (仅拦截解析结果); dry 走 _rule_decision 桩。
    """
    import app.harness.supervisor as supervisor_mod

    orig = supervisor_mod.get_llm_by_intent

    if mode == "live":

        def _factory(intent, modality=None, complexity=None, temperature=0.2):
            routed = orig(intent, modality=modality, complexity=complexity, temperature=temperature)
            real_structured = routed.with_structured_output(supervisor_mod.RoutingDecision)

            async def invoke(messages):
                decision = await real_structured.ainvoke(messages)
                captured[_extract_text(messages)] = decision
                return decision

            return _FakeRouted(_Structured(invoke))

    else:

        def _factory(intent, modality=None, complexity=None, temperature=0.2):
            async def invoke(messages):
                text = _extract_text(messages)
                decision = _rule_decision(text)
                captured[text] = decision
                return decision

            return _FakeRouted(_Structured(invoke))

    supervisor_mod.get_llm_by_intent = _factory
    try:
        yield captured
    finally:
        supervisor_mod.get_llm_by_intent = orig


# ---------- 单条执行 ----------
def _build_state(case: RoutingCase) -> dict:
    state: dict = {"messages": [HumanMessage(content=case.input)]}
    if case.mode and case.mode != "chat":
        state["mode"] = case.mode
    if case.images:
        state["images"] = [STUB_IMAGE]
    if case.iteration is not None:
        state["iteration_count"] = case.iteration
    return state


async def _eval_one(case: RoutingCase, spy_log: dict[str, sup.RoutingDecision],
                    sem: asyncio.Semaphore) -> dict:
    async with sem:
        result = await sup.supervisor_node(_build_state(case))
    decision = spy_log.pop(case.input, None)
    resolved = result.get("next_agent", "finish")
    if decision is not None:
        predicted = decision.skill_name or decision.next_agent
        confidence = round(decision.confidence, 3)
        semantic = decision.next_agent
    else:  # 规则前置分支 (images/document/迭代/空文本), 无 LLM
        predicted = resolved
        confidence = None
        semantic = resolved
    return {
        "id": case.id,
        "input": case.input,
        "category": case.category,
        "expected": case.expected_label,
        "predicted": predicted,
        "semantic": semantic,
        "resolved": resolved,
        "confidence": confidence,
        "skill": (decision.skill_name if decision is not None else None),
    }


async def run_routing_eval(cases: list[RoutingCase], mode: str = "live",
                           limit: Optional[int] = None,
                           concurrency: int = 5) -> dict:
    """逐条跑 supervisor 语义路由并汇总指标。mode: live | dry。"""
    picked = cases[:limit] if limit else cases
    spy_log: dict[str, sup.RoutingDecision] = {}
    sem = asyncio.Semaphore(concurrency)
    outcomes: list[dict] = []
    async with routing_spy(mode, spy_log):
        outcomes = await asyncio.gather(*[_eval_one(c, spy_log, sem) for c in picked])

    expected = [o["expected"] for o in outcomes]
    predicted = [o["predicted"] for o in outcomes]
    categories = [o["category"] for o in outcomes]
    metrics = compute_routing_metrics(expected, predicted, categories)
    failures = [
        {k: o[k] for k in ("id", "input", "expected", "predicted", "semantic", "resolved", "confidence")}
        for o in outcomes if o["expected"] != o["predicted"]
    ]
    return {
        "layer": "routing",
        "mode": mode,
        **metrics,
        "failures": failures[:20],
        "total_failures": len(failures),
    }


# ---------- CLI ----------
def _fmt_report(result: dict) -> str:
    lines = [
        f"Layer2 路由准确性评估 ({result['layer']}, mode={result['mode']})",
        f"total={result['total']} correct={result['correct']} "
        f"accuracy={result['accuracy']} macro_f1={result['macro_f1']}",
        "--- per label ---",
    ]
    for label, m in result["per_label"].items():
        if m["support"] == 0:
            continue
        lines.append(
            f"  {label:<18} precision={m['precision']:<6} recall={m['recall']:<6} "
            f"f1={m['f1']:<6} support={m['support']}"
        )
    lines.append("--- by category ---")
    for cat, m in result["by_category"].items():
        lines.append(f"  {cat:<14} total={m['total']:<3} correct={m['correct']:<3} "
                     f"accuracy={m['accuracy']}")
    if result["failures"]:
        lines.append(f"--- failures ({result['total_failures']}, 前20) ---")
        for f in result["failures"]:
            lines.append(
                f"  {f['id']}: expected={f['expected']} predicted={f['predicted']} "
                f"(semantic={f['semantic']}, resolved={f['resolved']}, conf={f['confidence']})\n"
                f"      input: {f['input'][:80]}"
            )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Layer2 路由准确性评估")
    parser.add_argument("--mode", choices=["live", "dry"], default="live")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--json", action="store_true", help="仅输出 JSON")
    args = parser.parse_args()

    cases = load_golden()
    result = asyncio.run(run_routing_eval(cases, mode=args.mode, limit=args.limit))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(_fmt_report(result))


if __name__ == "__main__":
    main()
