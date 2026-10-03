"""Evaluation 层 — Layer 4 E2E 场景评估引擎。

所属层级: Evaluation / Layer 4

- live: 把用户输入送进完整 LangGraph(build_graph + MemorySaver), 用一次 astream_events(v2)
  捕获执行节点链与 MCP 工具, drain 后 aget_state 取最终答案, 对每个 scenario 的 checks 逐条判定。
- dry : 零 LLM/零网络/零 graph —— 用 scenario 自身声明的期望合成自洽 trace, 所有 check 自洽通过,
       仅冒烟 数据集/check 判定/聚合/持久化 管线; 各 check 判错分支由单测注入合成 trace 覆盖。
- 通过口径: scenario passed = 无 trace.error 且全部 check ok; 外部依赖缺失(live 异常)计 failed 进 failures。

CLI: python -m app.evaluation.test_e2e --mode dry|live [--json]
"""
import argparse
import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("eval.e2e")

DEFAULT_SCENARIOS = Path(__file__).resolve().parent / "golden_datasets" / "e2e_scenarios.json"

# 合法 check 类型
CHECK_TYPES = {"routing_check", "multi_agent_check", "output_pattern", "mcp_tool_check", "format_check"}
_REQUIRED_PARAM = {
    "routing_check": "expected",
    "multi_agent_check": "agents",
    "output_pattern": "pattern",
    "mcp_tool_check": "tool",
    "format_check": None,  # 至少 min_length / must_not 其一
}


# ---------- scenario 数据集 ----------
@dataclass(frozen=True)
class E2ECase:
    id: str
    name: str
    category: str
    mode: str
    input: str
    checks: tuple[dict, ...]  # 每项 {"type": ..., ...params}


def load_e2e_scenarios(path: str | Path = DEFAULT_SCENARIOS) -> list[E2ECase]:
    """加载并校验 e2e_scenarios: 必需字段、check type 合法、参数齐全、id 唯一。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    seen: set[str] = set()
    cases: list[E2ECase] = []
    for raw in data:
        missing = {"id", "name", "category", "input", "checks"} - set(raw)
        if missing:
            raise ValueError(f"scenario 缺少字段: {sorted(missing)} @ {raw.get('id', '?')}")
        cid = raw["id"]
        if cid in seen:
            raise ValueError(f"scenario id 重复: {cid}")
        seen.add(cid)
        checks = raw["checks"]
        if not isinstance(checks, list) or not checks:
            raise ValueError(f"scenario {cid}: checks 必须是非空列表")
        norm: list[dict] = []
        for spec in checks:
            t = spec["type"]
            if t not in CHECK_TYPES:
                raise ValueError(f"scenario {cid}: 未知 check type {t!r} (可选 {sorted(CHECK_TYPES)})")
            key = _REQUIRED_PARAM[t]
            if t == "format_check":
                if not (spec.get("min_length") is not None or spec.get("must_not")):
                    raise ValueError(f"scenario {cid}: format_check 需 min_length 或 must_not 至少其一")
            elif not spec.get(key):
                raise ValueError(f"scenario {cid}: {t} 缺少参数 {key}")
            if t == "multi_agent_check" and not (isinstance(spec["agents"], list) and spec["agents"]):
                raise ValueError(f"scenario {cid}: multi_agent_check.agents 必须是非空列表")
            norm.append(dict(spec))
        cases.append(E2ECase(
            id=cid, name=raw["name"], category=raw["category"],
            mode=raw.get("mode", "chat"), input=raw["input"], checks=tuple(norm),
        ))
    return cases


# ---------- 纯判定函数 (trace: dict | None) ----------
def check_routing(trace: dict, spec: dict) -> dict:
    expected = spec["expected"]
    actual = trace.get("route")
    return {"ok": expected == actual, "detail": f"expected={expected} actual={actual}"}


def check_multi_agent(trace: dict, spec: dict) -> dict:
    agents = spec["agents"]
    nodes = trace.get("nodes", [])
    remain = list(agents)
    for n in nodes:
        if remain and n == remain[0]:
            remain.pop(0)
    if remain:
        return {"ok": False,
                "detail": f"agents {agents} 未按序出现在 nodes {nodes} (缺 {remain})"}
    return {"ok": True, "detail": f"nodes={nodes} 含有序子序列 {agents}"}


def check_output_pattern(trace: dict, spec: dict) -> dict:
    pattern = spec["pattern"]
    answer = str(trace.get("final_answer", ""))
    if pattern in answer:
        return {"ok": True, "detail": f"final_answer 命中 pattern {pattern!r}"}
    return {"ok": False,
            "detail": f"final_answer 未含 pattern {pattern!r} (前 80 字: {answer[:80]!r})"}


def check_mcp_tool(trace: dict, spec: dict) -> dict:
    prefix = spec["tool"]
    tools = trace.get("tools", [])
    hit = next((t for t in tools if t.startswith(prefix)), None)
    if hit:
        return {"ok": True, "detail": f"命中 MCP 工具 {hit!r}"}
    return {"ok": False, "detail": f"无工具以 {prefix!r} 开头 (tools={tools})"}


def check_format(trace: dict, spec: dict) -> dict:
    answer = str(trace.get("final_answer", ""))
    reasons: list[str] = []
    min_len = spec.get("min_length")
    if min_len is not None and len(answer) < int(min_len):
        reasons.append(f"长度 {len(answer)} < {min_len}")
    for bad in spec.get("must_not") or []:
        if bad in answer:
            reasons.append(f"含禁止串 {bad!r}")
    return {"ok": not reasons, "detail": "; ".join(reasons) if reasons else "格式达标"}


EVAL_CHECKERS: dict[str, object] = {
    "routing_check": check_routing,
    "multi_agent_check": check_multi_agent,
    "output_pattern": check_output_pattern,
    "mcp_tool_check": check_mcp_tool,
    "format_check": check_format,
}


def evaluate_checks(trace: dict, checks: tuple[dict, ...]) -> dict:
    """逐条判定; 未知 type 计失败。返回 {all_ok, checks:[{type,ok,detail}]}。"""
    results = []
    for spec in checks:
        fn = EVAL_CHECKERS.get(spec["type"])
        if fn is None:
            results.append({"type": spec["type"], "ok": False,
                            "detail": f"unknown_check:{spec['type']}"})
            continue
        r = fn(trace, spec)
        results.append({"type": spec["type"], "ok": bool(r["ok"]),
                        "detail": str(r["detail"])})
    return {"all_ok": bool(results) and all(r["ok"] for r in results), "checks": results}


# ---------- trace 生产 ----------
def dry_trace(case: E2ECase) -> dict:
    """从 scenario 自身期望合成自洽 trace (dry: 零 LLM/网络/graph)。"""
    agents: list[str] = []
    for c in case.checks:
        if c["type"] == "multi_agent_check":
            for a in c["agents"]:
                if a not in agents:
                    agents.append(a)
    route = next((c["expected"] for c in case.checks
                  if c["type"] == "routing_check"), None)
    if route is None:
        route = agents[0] if agents else "finish"
    if route != "finish" and route not in agents:
        agents.insert(0, route)

    tools: list[str] = []
    for c in case.checks:
        if c["type"] == "mcp_tool_check":
            tools.append(c["tool"] + "get_issues")  # 形如 mcp_github_get_issues, 满足 startswith(tool)

    patterns = [c["pattern"] for c in case.checks if c["type"] == "output_pattern"]
    base = "\n".join(patterns) if patterns else case.name
    min_len = max((int(c["min_length"]) for c in case.checks
                   if c["type"] == "format_check" and c.get("min_length") is not None),
                  default=0)
    if min_len and base and len(base) < min_len:
        base = base * (min_len // len(base) + 1)

    return {
        "nodes": agents,
        "tools": tools,
        "final_answer": base if base else case.name,
        "route": route,
        "error": None,
    }


async def produce_trace(case: E2ECase) -> dict:
    """live: 真实跑完整 LangGraph, 捕获节点链/MCP 工具/最终答案/route。

    依赖缺失或运行异常 -> trace.error 记原因(严格计 failed), 不抛断批。
    """
    import uuid

    from langgraph.checkpoint.memory import MemorySaver
    from langchain_core.messages import HumanMessage

    from app.harness.graph import build_graph

    trace = {"nodes": [], "tools": [], "final_answer": "", "route": "finish", "error": None}
    thread_id = f"eval:{uuid.uuid4()}"
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 10}
    try:
        graph = build_graph(MemorySaver())
        inputs = {"messages": [HumanMessage(content=case.input)], "mode": case.mode}
        async for event in graph.astream_events(inputs, config=config, version="v2"):
            evt = event.get("event")
            name = event.get("name") or ""
            if evt == "on_chain_start" and name.startswith("hooked_"):
                node = name[len("hooked_"):]
                if node != "supervisor" and (not trace["nodes"] or trace["nodes"][-1] != node):
                    trace["nodes"].append(node)
            elif evt in ("on_tool_start", "on_tool_end") and name:
                if name not in trace["tools"]:
                    trace["tools"].append(name)
        snap = await graph.aget_state(config)
        vals = snap.values if snap else {}
        fa = (vals or {}).get("final_answer")
        trace["final_answer"] = fa if isinstance(fa, str) else ""
        trace["route"] = trace["nodes"][0] if trace["nodes"] else "finish"
        return trace
    except Exception as e:  # noqa: BLE001 — 依赖缺失/异常计 failed, 不断批
        logger.warning("E2E trace 失败 scenario=%s: %s", case.id, e)
        trace["error"] = f"{type(e).__name__}: {str(e)[:300]}"
        return trace


# ---------- 聚合 ----------
def _counters() -> dict:
    return {"n": 0, "passed": 0}


async def run_e2e_eval(
    scenarios: list[E2ECase],
    mode: str = "live",
    limit: int | None = None,
    producer=None,
) -> dict:
    """逐条生产 trace -> 判定 checks -> 聚合。producer 可注入(单测)。"""
    mode = mode if mode in ("live", "dry") else "live"
    subset = list(scenarios) if limit is None else list(scenarios)[:limit]

    by_category: dict[str, dict] = {}
    by_check: dict[str, dict] = {}
    failures: list[dict] = []
    per_scenario: list[dict] = []
    passed = 0

    for case in subset:
        if producer is not None:
            trace = await producer(case)
        else:
            trace = dry_trace(case) if mode == "dry" else await produce_trace(case)

        cat = by_category.setdefault(case.category, _counters())
        cat["n"] += 1

        entry = {"id": case.id, "name": case.name, "category": case.category, "ok": False}
        if trace.get("error"):
            reason = f"trace_error: {trace['error']}"
            per_scenario.append({**entry, "checks": [], "reason": reason})
            failures.append({
                "id": case.id, "name": case.name, "category": case.category, "ok": False,
                "reason": reason, "error": trace["error"],
                "nodes": trace.get("nodes", []), "tools": trace.get("tools", []),
                "output_excerpt": str(trace.get("final_answer", ""))[:200],
            })
            continue

        verdict = evaluate_checks(trace, case.checks)
        ok = bool(verdict["all_ok"])
        per_scenario.append({**entry, "ok": ok, "checks": verdict["checks"]})
        if ok:
            passed += 1
            cat["passed"] += 1
        for r in verdict["checks"]:
            bc = by_check.setdefault(r["type"], _counters())
            bc["n"] += 1
            if r["ok"]:
                bc["passed"] += 1
        if not ok:
            bad = [r for r in verdict["checks"] if not r["ok"]]
            failures.append({
                "id": case.id, "name": case.name, "category": case.category, "ok": False,
                "reason": f"{len(bad)}/{len(verdict['checks'])} check 未通过",
                "checks": bad,
                "nodes": trace.get("nodes", []), "tools": trace.get("tools", []),
                "output_excerpt": str(trace.get("final_answer", ""))[:200],
            })

    return {
        "layer": "e2e",
        "mode": mode,
        "total": len(subset),
        "passed": passed,
        "pass_rate": round(passed / len(subset), 4) if subset else 0.0,
        "by_category": by_category,
        "by_check": by_check,
        "scenarios": per_scenario,
        "failures": failures,
    }


# ---------- CLI ----------
def _fmt_report(result: dict) -> str:
    lines = [f"[e2e] mode={result['mode']} passed={result['passed']}/{result['total']} "
             f"pass_rate={result['pass_rate']}"]
    lines.append("  by_category:")
    for cat, st in sorted(result["by_category"].items()):
        lines.append(f"    - {cat:<10} {st['passed']}/{st['n']}")
    lines.append("  by_check:")
    for c, st in sorted(result["by_check"].items()):
        lines.append(f"    - {c:<18} {st['passed']}/{st['n']}")
    for f in result["failures"]:
        lines.append(f"  ⚠ {f['id']} [{f['category']}] {f['name']}: {f['reason']}")
        if f.get("checks"):
            for c in f["checks"]:
                lines.append(f"      - {c['type']}: {c['detail'][:120]}")
        if f.get("error"):
            lines.append(f"      - error: {f['error'][:200]}")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Layer 4 E2E 场景评估")
    ap.add_argument("--mode", choices=["live", "dry"], default="dry")
    ap.add_argument("--json", action="store_true", help="输出原始 JSON")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    result = asyncio.run(run_e2e_eval(
        load_e2e_scenarios(), mode=args.mode, limit=args.limit,
    ))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(_fmt_report(result))


if __name__ == "__main__":
    main()
