"""Evaluation 层 — Layer 3 输出质量评估引擎 (LLM Judge)。

所属层级: Evaluation / Layer 3

- live: 对每条 golden 独立调用对应 Agent 节点产出 final_answer, 再交 LLM Judge 打分。
- dry : 候选输出 = golden reference, Judge 用确定性 StubJudge 满分 —— 零 LLM/零网络,
       仅冒烟整条管线(数据集/聚合/持久化/报告)。
- 输出: 各 Agent(即各 judge kind)平均分 + 最低分案例 + 低于 fail_below 的 failures。

CLI: python -m app.evaluation.test_output_quality --mode dry|live [--json]
"""
import argparse
import asyncio
import importlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from langchain_core.messages import HumanMessage

from app.config import settings
from app.evaluation.llm_judge import KIND_CRITERIA, llm_judge_one

logger = logging.getLogger("eval.quality")

DEFAULT_GOLDEN = Path(__file__).resolve().parent / "golden_datasets" / "output_golden.json"

# agent -> judge kind 固定映射 (golden 校验用)
AGENT_JUDGE: dict[str, str] = {
    "coder": "code",
    "writer": "writing",
    "web_search": "search",
}

_AGENT_MODULES = {
    "coder": ("app.agents.coder", "CoderAgent"),
    "writer": ("app.agents.writer", "WriterAgent"),
    "web_search": ("app.agents.web_search_agent", "WebSearchAgent"),
}


# ---------- golden 数据集 ----------
@dataclass(frozen=True)
class QualityCase:
    id: str
    agent: str
    judge: str
    input: str
    reference: str


def load_output_golden(path: str | Path = DEFAULT_GOLDEN) -> list[QualityCase]:
    """加载并校验 output_golden: agent/judge 合法且映射一致。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    cases: list[QualityCase] = []
    for raw in data:
        if not isinstance(raw, dict):
            raise ValueError(f"golden 条目非法: {raw!r}")
        missing = {"id", "agent", "judge", "input", "reference"} - set(raw)
        if missing:
            raise ValueError(f"golden 条目缺少字段: {sorted(missing)} @ {raw.get('id', '?')}")
        agent = raw["agent"]
        judge = raw["judge"]
        if agent not in AGENT_JUDGE:
            raise ValueError(f"golden {raw['id']}: 未知 agent {agent!r}")
        if judge != AGENT_JUDGE[agent]:
            raise ValueError(f"golden {raw['id']}: agent={agent} 应映射 judge={AGENT_JUDGE[agent]}, 实为 {judge!r}")
        cases.append(QualityCase(
            id=raw["id"], agent=agent, judge=judge,
            input=raw["input"], reference=raw["reference"],
        ))
    return cases


# ---------- live 候选产出: 独立跑单 Agent 节点 ----------
async def produce_answer(agent: str, question: str) -> str:
    """调用对应 Agent 节点 .run(), 返回 final_answer(最终用户可见文本)。"""
    mod_name, cls_name = _AGENT_MODULES[agent]
    mod = importlib.import_module(mod_name)
    cls = getattr(mod, cls_name)
    state = {"messages": [HumanMessage(content=question)]}
    out = await cls().run(state)
    answer = (out or {}).get("final_answer")
    return answer if isinstance(answer, str) else ""


# ---------- dry 桩 ----------
class StubJudge:
    """dry: 候选输出 = reference(自洽), 一律满分。确定性、零 LLM。"""

    async def __call__(self, kind: str, question: str, output: str,
                       reference: str | None = None) -> dict:
        return {
            "criteria": {c: 5.0 for c in KIND_CRITERIA.get(kind, [])},
            "overall": 5.0,
            "comment": "dry stub: 候选=参考答案 自洽满分",
        }


# ---------- 纯聚合函数 ----------
def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 3) if values else 0.0


def agent_scores(results: list[dict]) -> dict:
    """纯函数: 按 agent 聚合平均分/每维度均值/最低分案例。供报告与单测。"""
    by_agent: dict[str, list[dict]] = {}
    for r in results:
        by_agent.setdefault(r["agent"], []).append(r)

    agents: dict[str, dict] = {}
    for agent, rows in by_agent.items():
        judge = rows[0]["judge"]
        criteria_keys = KIND_CRITERIA.get(judge, [])
        overalls = [r["overall"] for r in rows]
        worst = min(rows, key=lambda r: r["overall"])
        agents[agent] = {
            "n": len(rows),
            "judge": judge,
            "overall_avg": _mean(overalls),
            "min_overall": round(worst["overall"], 3),
            "min_case": {"id": worst["id"], "overall": round(worst["overall"], 3)},
            "criteria_avg": {
                c: _mean([r["criteria"].get(c, 0.0) for r in rows])
                for c in criteria_keys
            },
        }
    return agents


# ---------- 主流程 ----------
async def run_quality_eval(
    cases: list[QualityCase],
    mode: str = "live",
    limit: int | None = None,
    judge=None,
    fail_below: float | None = None,
) -> dict:
    """逐条产出候选 -> 打分 -> 聚合。judge 可注入(单测); mode=dry 默认 StubJudge。"""
    mode = mode if mode in ("live", "dry") else "live"
    subset = list(cases) if limit is None else list(cases)[:limit]
    fail_below = settings.EVAL_QUALITY_MIN_SCORE if fail_below is None else float(fail_below)

    judge_impl = judge if judge is not None else (
        StubJudge() if mode == "dry" else llm_judge_one
    )
    judged_by = "llm" if (judge is None and mode == "live") else ("stub" if mode == "dry" else "inject")

    scored: list[dict] = []
    errors: list[dict] = []
    for case in subset:
        output = case.reference if mode == "dry" else await produce_answer(case.agent, case.input)
        try:
            verdict = await judge_impl(case.judge, case.input, output, case.reference)
        except Exception as e:  # noqa: BLE001 — 单个 judge 异常不中断整批
            logger.warning("case=%s judge 异常: %s", case.id, e)
            verdict = None
        if verdict is None:
            errors.append({"id": case.id, "agent": case.agent, "reason": "judge_no_verdict"})
            continue
        scored.append({
            "id": case.id,
            "agent": case.agent,
            "judge": case.judge,
            "overall": round(float(verdict["overall"]), 3),
            "criteria": {k: round(float(v), 3) for k, v in verdict["criteria"].items()},
            "comment": str(verdict.get("comment", "")),
            "output": output,
        })

    failures = [
        {
            "id": r["id"], "agent": r["agent"], "judge": r["judge"],
            "overall": r["overall"], "criteria": r["criteria"],
            "comment": r["comment"],
            "output_excerpt": r["output"][:200],
        }
        for r in scored if r["overall"] < fail_below
    ]

    return {
        "layer": "quality",
        "mode": mode,
        "total": len(subset),
        "scored": len(scored),
        "judged_by": judged_by,
        "timeout_s": settings.EVAL_JUDGE_TIMEOUT_S,
        "fail_below": fail_below,
        "agents": agent_scores(scored),
        "cases": [
            {"id": r["id"], "agent": r["agent"], "judge": r["judge"],
             "overall": r["overall"], "criteria": r["criteria"]}
            for r in scored
        ],
        "errors": errors,
        "failures": failures,
    }


# ---------- CLI ----------
def _fmt_scoreboard(result: dict) -> str:
    lines = [f"[quality] mode={result['mode']} scored={result['scored']}/{result['total']} "
             f"judged_by={result['judged_by']} fail_below={result['fail_below']}"]
    for agent, st in result["agents"].items():
        crit = ", ".join(f"{k}={v}" for k, v in st["criteria_avg"].items())
        lines.append(
            f"  - {agent:<10} n={st['n']} overall_avg={st['overall_avg']} "
            f"min={st['min_case']} | {crit}"
        )
    if result["failures"]:
        lines.append(f"  ⚠ failures ({len(result['failures'])}):")
        for f in result["failures"]:
            lines.append(f"    - {f['id']} ({f['agent']}) overall={f['overall']}: {f['comment'][:80]}")
    if result["errors"]:
        lines.append(f"  ⚠ errors ({len(result['errors'])}):")
        for e in result["errors"]:
            lines.append(f"    - {e['id']} ({e['agent']}) {e['reason']}")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Layer 3 输出质量评估 (LLM Judge)")
    ap.add_argument("--mode", choices=["live", "dry"], default="dry")
    ap.add_argument("--json", action="store_true", help="输出原始 JSON")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    result = asyncio.run(run_quality_eval(
        load_output_golden(), mode=args.mode, limit=args.limit,
    ))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(_fmt_scoreboard(result))


if __name__ == "__main__":
    main()
