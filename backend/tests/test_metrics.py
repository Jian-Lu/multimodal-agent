"""Evaluation 层 — Layer 1 性能指标采集单元测试。

所属层级: Evaluation / Layer 1

覆盖: metrics_collector 统计正确性/ring 上限/计数器/reset/sink,
      TimingHook 经 HookManager.wrap 的端到端埋点, LLM Router / Supervisor 埋点。
"""
import asyncio

import pytest

from app.evaluation.metrics_collector import MetricsCollector, get_metrics_collector
from app.evaluation.timing_hook import hook_post_timing_metrics
from app.harness.hooks import HookManager


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clean_collector():
    """每例前清空全局收集器, 用例相互隔离。"""
    get_metrics_collector().reset()
    yield
    get_metrics_collector().reset()


def _find(entries, kind, tag_key=None, tag_val=None):
    """在 snapshot 结果中按 kind(+tags) 找条目。"""
    for e in entries:
        if e["kind"] != kind:
            continue
        if tag_key is not None and e["tags"].get(tag_key) != tag_val:
            continue
        return e
    return None


# ---------- metrics_collector ----------

def test_snapshot_stats_1_to_100():
    c = MetricsCollector(ring_size=1000)
    for i in range(1, 101):
        c.record("lat", value=float(i), node="x")
    snap = c.snapshot(window_s=None)
    e = _find(snap, "lat")
    assert e is not None
    assert e["count"] == 100
    assert e["min"] == 1.0
    assert e["mean"] == 50.5
    assert e["max"] == 100.0
    assert e["p50"] == 50.0
    assert e["p95"] == 95.0
    assert e["p99"] == 99.0


def test_ring_bounded_by_maxlen():
    c = MetricsCollector(ring_size=5)
    for i in range(20):
        c.record("lat", value=float(i), node="x")
    e = _find(c.snapshot(window_s=None), "lat")
    assert e["count"] == 5
    assert e["max"] == 19.0  # 只保留最后 5 条


def test_counter_total_and_count():
    c = get_metrics_collector()
    c.incr("token_usage", amount=3)
    c.record("token_usage", count=7)
    e = _find(c.snapshot(window_s=None), "token_usage")
    assert e is not None
    assert e["total"] == 10
    assert e["count"] == 2


def test_counter_separated_by_tags():
    c = get_metrics_collector()
    c.incr("token_usage", amount=5, intent="code")
    c.incr("token_usage", amount=9, intent="chat")
    snap = c.snapshot(window_s=None)
    assert _find(snap, "token_usage", "intent", "code")["total"] == 5
    assert _find(snap, "token_usage", "intent", "chat")["total"] == 9


def test_reset_clears():
    c = get_metrics_collector()
    c.record("lat", value=1.0, node="x")
    c.incr("tok", amount=1)
    c.reset()
    assert c.snapshot(window_s=None) == []
    assert c.series_count == 0


def test_sink_receives_events():
    got = []
    c = get_metrics_collector()
    c.set_sink(lambda ev: got.append(ev))
    c.record("lat", value=2.5, node="x")
    c.record("tok", count=4)
    c.set_sink(None)
    assert len(got) == 2
    assert got[0]["kind"] == "lat" and got[0]["value"] == 2.5
    assert got[1]["kind"] == "tok" and got[1]["count"] == 4


# ---------- TimingHook 端到端 ----------

def test_timing_hook_records_node_latency():
    async def node(state):
        await asyncio.sleep(0.01)  # ~10ms, 确保耗时 > 0
        return {"a": 1}

    mgr = HookManager()
    mgr.register_fn("post", "test_timing", hook_post_timing_metrics, node="*")
    run(mgr.wrap(node, "coder")({}))

    snap = get_metrics_collector().snapshot(window_s=None, kinds=["hook_latency"])
    e = _find(snap, "hook_latency", "node", "coder")
    assert e is not None
    assert e["count"] == 1
    assert e["max"] > 0
    assert "thread_id" in e["tags"]


# ---------- LLM Router 埋点 ----------

def test_router_latency_recorded(monkeypatch):
    from app.llm import factory as factory_mod

    class _Dummy:
        pass

    monkeypatch.setattr(factory_mod, "_build", lambda name, temperature=0.2: _Dummy())
    factory_mod.get_llm_by_intent("code")

    snap = get_metrics_collector().snapshot(window_s=None, kinds=["router_latency"])
    e = _find(snap, "router_latency", "intent", "code")
    assert e is not None
    assert e["count"] == 1
    assert e["tags"]["model"] == factory_mod.settings.ROUTE_CODE_MODEL


# ---------- Supervisor 埋点 ----------

def test_supervisor_latency_recorded():
    from app.harness import supervisor as sup
    from app.harness.state import RoutingDecision

    decision = RoutingDecision(
        next_agent="coder", skill_name=None, reasoning="写代码", confidence=0.9
    )
    result = sup._resolve_decision(decision, it=1, latency_ms=12.3)

    assert result["next_agent"] == "coder"
    snap = get_metrics_collector().snapshot(window_s=None, kinds=["supervisor_latency"])
    e = _find(snap, "supervisor_latency", "next_agent", "coder")
    assert e is not None
    assert e["max"] == 12.3
    assert e["tags"]["outcome"] == "ok"


def test_supervisor_illegal_agent_still_records():
    from app.harness import supervisor as sup
    from app.harness.state import RoutingDecision

    decision = RoutingDecision(
        next_agent="coder", skill_name=None, reasoning="x", confidence=0.9
    )
    sup._resolve_decision(decision, it=1, latency_ms=5.0)

    snap = get_metrics_collector().snapshot(window_s=None, kinds=["supervisor_latency"])
    assert _find(snap, "supervisor_latency") is not None
