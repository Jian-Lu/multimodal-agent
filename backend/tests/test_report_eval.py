"""Evaluation 层 — Phase 21 报告生成器 + GET /report、/report/history 单元测试。

所属层级: Evaluation / Phase 21 (全部离线: 纯函数 + 直调 handler, 零 LLM/网络/真实 graph)
"""
import asyncio
import json
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.v1.evaluation import get_report, get_report_history
from app.db.base import Base
from app.evaluation.report_generator import (
    digest_run,
    render_html,
    render_report_json,
    render_text,
)
from app.models import EvaluationRun, User


def run(coro):
    return asyncio.run(coro)


def _run_dict(**kw) -> dict:
    base = {
        "run_id": "r1", "layer": "routing", "mode": "dry", "status": "success",
        "created_at": "2026-09-06T10:00:00", "duration_ms": 123,
        "summary": {}, "failures": [],
    }
    base.update(kw)
    return base


# ---------- 纯函数: digest_run ----------

def test_digest_math_and_verdicts():
    d = digest_run(_run_dict(layer="routing",
                             summary={"accuracy": 0.941176, "total": 34},
                             failures=[{"id": "r005", "reason": "期望 coder 实得 web_search"}]))
    assert d["verdict"] == "warn"
    assert d["score"] == 94.1
    assert d["score_label"] == "路由准确率"
    assert d["failures"] == 1 and d["total"] == 34

    d = digest_run(_run_dict(layer="quality", summary={"agents": {
        "coder": {"overall_avg": 4.2, "n": 4},
        "writer": {"overall_avg": 3.6, "n": 4}}}))
    assert d["score"] == 78.0  # (4.2+3.6)/2 /5 *100
    assert d["verdict"] == "ok"

    d = digest_run(_run_dict(layer="e2e", summary={"pass_rate": 0.8333, "total": 12, "passed": 10}))
    assert d["score"] == 83.3
    assert d["score_label"] == "E2E 通过率"


def test_digest_fail_verdict_and_missing_keys():
    # status=error -> fail(即使无 failures); 缺 score 键 -> None
    d = digest_run(_run_dict(layer="e2e", status="error", summary={}))
    assert d["verdict"] == "fail"
    assert d["score"] is None
    assert d["failures"] == 0
    # quality 无 agents -> 无分数
    d = digest_run(_run_dict(layer="quality", summary={}))
    assert d["score"] is None and d["total"] is None
    # failures 非 list 容错
    d = digest_run(_run_dict(layer="routing", summary={"accuracy": 1.0}, failures="oops"))
    assert d["verdict"] == "ok" and d["failures"] == 0
    # score 越界 clamp
    d = digest_run(_run_dict(layer="e2e", summary={"pass_rate": 9.0}))
    assert d["score"] == 100.0


# ---------- 纯函数: render_report_json ----------

def test_report_json_shape_and_missing():
    runs = [
        _run_dict(run_id="a", layer="routing", summary={"accuracy": 0.9}),
        _run_dict(run_id="b", layer="quality", summary={"agents": {"coder": {"overall_avg": 4.0}}}),
        _run_dict(run_id="c", layer="e2e", summary={"pass_rate": 1.0}),
    ]
    j = render_report_json(runs, report_type="aggregate")
    assert j["type"] == "aggregate"
    assert sorted(j["layers"]) == ["e2e", "quality", "routing"]
    assert j["missing"] == []
    assert len(j["runs"]) == 3
    assert j["runs"][0]["summary"]["accuracy"] == 0.9

    j = render_report_json([], report_type="aggregate")
    assert j["layers"] == {}
    assert j["missing"] == ["routing", "quality", "e2e"]
    assert j["runs"] == []


# ---------- 纯函数: render_text / render_html ----------

def test_render_text_markers_and_failures():
    ok_run = _run_dict(run_id="ok1", layer="e2e", summary={"pass_rate": 1.0}, failures=[])
    warn_run = _run_dict(run_id="w1", layer="routing", summary={"accuracy": 0.8},
                         failures=[{"id": "r005", "reason": "期望 coder 实得 web_search"}])
    fail_run = _run_dict(run_id="f1", layer="quality", status="error", summary={},
                         failures=[])
    txt = render_text([ok_run, warn_run, fail_run])
    assert "✅" in txt and "⚠" in txt and "❌" in txt
    assert "E2E 通过率" not in txt  # text 用 layer_label(中文)
    assert "输出质量" in txt
    assert "期望 coder 实得 web_search" in txt
    assert "w1" in txt
    assert render_text([]) == "[评估报告] (evaluation_runs 无记录)"


def test_render_text_quality_comment_surfaced():
    run = _run_dict(run_id="q9", layer="quality", summary={"agents": {"writer": {"overall_avg": 2.0}}},
                    failures=[{"id": "q003", "agent": "writer", "judge": "writing",
                               "overall": 2.0, "comment": "结构松散, 信息密度低"}])
    txt = render_text([run])
    assert "q003" in txt
    assert "结构松散" in txt
    assert "- judge: writing" in txt and "- overall: 2.0" in txt


def test_render_html_self_contained_and_escaped():
    run = _run_dict(layer="routing", summary={"accuracy": 0.9},
                    failures=[{"id": "x1", "reason": '<script>alert(1)</script> & "bad"'}])
    h = render_html([run])
    assert h.startswith("<!DOCTYPE html>")
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in h
    assert "<script>" not in h
    assert "&amp;" in h
    assert "<details>" in h and "失败明细 (1)" in h
    assert render_html([]).startswith("<!DOCTYPE html>")


# ---------- handler 直调: DB fixture ----------

def _make_user(user_id: str) -> User:
    return User(id=user_id, email=f"{user_id}@example.com",
                username=user_id, hashed_password="x")


def _eval_run(run_id: str, layer: str, created_at: datetime,
              summary: dict | None = None, failures: list | None = None,
              mode: str = "dry", status: str = "success", duration_ms: int = 1) -> EvaluationRun:
    return EvaluationRun(
        id=run_id, layer=layer, mode=mode, status=status,
        summary_json=json.dumps(summary or {}, ensure_ascii=False),
        failures_json=json.dumps(failures or [], ensure_ascii=False),
        duration_ms=duration_ms, created_at=created_at,
    )


async def _setup():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


# 直调 handler 时 FastAPI 不会注入 Query 默认值, 需显式传参 (沿用 test_sessions 直调约定)
async def _report(db, user, **kw) -> dict:
    kw.setdefault("run_id", None)
    kw.setdefault("format", "json")
    return await get_report(user=user, db=db, **kw)


async def _history(db, user, **kw) -> dict:
    kw.setdefault("layer", None)
    kw.setdefault("limit", 50)
    return await get_report_history(user=user, db=db, **kw)


def test_report_aggregate_latest_per_layer():
    async def _run():
        engine, maker = await _setup()
        base = datetime(2026, 9, 6, 8, 0, 0)
        async with maker() as db:
            db.add(_make_user("u1"))
            # e2e 两条, routing/quality 各一条
            db.add(_eval_run("e_old", "e2e", base, {"pass_rate": 0.5}))
            db.add(_eval_run("e_new", "e2e", base + timedelta(hours=2), {"pass_rate": 1.0}))
            db.add(_eval_run("r1", "routing", base + timedelta(hours=1), {"accuracy": 0.9}))
            db.add(_eval_run("q1", "quality", base + timedelta(hours=3),
                             {"agents": {"coder": {"overall_avg": 4.0}}}))
            await db.commit()
        async with maker() as db:
            u = await db.get(User, "u1")
            res = await _report(db, u)
            assert res["code"] == 0
            data = res["data"]
            assert data["type"] == "aggregate"
            assert sorted(data["layers"]) == ["e2e", "quality", "routing"]
            assert data["missing"] == []
            assert len(data["runs"]) == 3
            run_ids = {r["run_id"] for r in data["runs"]}
            assert "e_old" not in run_ids and "e_new" in run_ids  # 每层取最新
            assert data["layers"]["e2e"]["score"] == 100.0
            assert data["layers"]["quality"]["score"] == 80.0  # 4.0/5*100
        await engine.dispose()
    run(_run())


def test_report_run_id_single_and_404():
    async def _run():
        engine, maker = await _setup()
        async with maker() as db:
            db.add(_make_user("u1"))
            db.add(_eval_run("solo", "routing", datetime(2026, 9, 6, 8, 0, 0), {"accuracy": 0.8}))
            await db.commit()
        async with maker() as db:
            u = await db.get(User, "u1")
            res = await _report(db, u, run_id="solo")
            assert res["code"] == 0
            data = res["data"]
            assert data["type"] == "single"
            assert len(data["runs"]) == 1
            assert data["runs"][0]["run_id"] == "solo"
            assert data["layers"]["routing"]["verdict"] == "ok"
            # 不存在
            res = await _report(db, u, run_id="nope")
            assert res["code"] == 404
        await engine.dispose()
    run(_run())


def test_report_formats_text_html_and_bad():
    async def _run():
        engine, maker = await _setup()
        async with maker() as db:
            db.add(_make_user("u1"))
            db.add(_eval_run("w1", "routing", datetime(2026, 9, 6, 8, 0, 0), {"accuracy": 0.8},
                             failures=[{"id": "r005", "reason": "期望 coder 实得 web_search"}]))
            await db.commit()
        async with maker() as db:
            u = await db.get(User, "u1")
            t = await _report(db, u, format="text")
            assert not isinstance(t, dict)          # 非信封, 原文
            assert "✅" in t.body.decode("utf-8") or "⚠" in t.body.decode("utf-8")
            assert "期望 coder 实得 web_search" in t.body.decode("utf-8")
            h = await _report(db, u, format="html")
            body = h.body.decode("utf-8")
            assert body.startswith("<!DOCTYPE html>")
            # 默认 json 信封
            res = await _report(db, u)
            assert res["code"] == 0 and res["data"]["type"] == "aggregate"
            # 非法 format
            bad = await _report(db, u, format="xml")
            assert bad["code"] == 400
        await engine.dispose()
    run(_run())


def test_report_no_rows():
    async def _run():
        engine, maker = await _setup()
        async with maker() as db:
            db.add(_make_user("u1"))
            await db.commit()
        async with maker() as db:
            u = await db.get(User, "u1")
            res = await _report(db, u)
            data = res["data"]
            assert data["layers"] == {}
            assert data["missing"] == ["routing", "quality", "e2e"]
            assert data["runs"] == []
        await engine.dispose()
    run(_run())


def test_history_filter_limit_order_and_bad_layer():
    async def _run():
        engine, maker = await _setup()
        base = datetime(2026, 9, 6, 9, 0, 0)
        async with maker() as db:
            db.add(_make_user("u1"))
            rows = [
                _eval_run("a", "routing", base, {"accuracy": 0.9}),
                _eval_run("b", "quality", base + timedelta(minutes=1),
                          {"agents": {"coder": {"overall_avg": 4.0}}}),
                _eval_run("c", "e2e", base + timedelta(minutes=2), {"pass_rate": 1.0}),
                _eval_run("d", "routing", base + timedelta(minutes=3), {"accuracy": 0.7}),
            ]
            db.add_all(rows)
            await db.commit()
        async with maker() as db:
            u = await db.get(User, "u1")
            res = await _history(db, u)
            assert res["code"] == 0
            data = res["data"]
            assert data["total"] == 4
            assert [i["id"] for i in data["items"]] == ["d", "c", "b", "a"]  # 降序
            assert data["items"][0]["score"] == 70.0
            assert {"id", "layer", "mode", "status", "duration_ms", "created_at",
                    "verdict", "score", "score_label", "failures", "total"} <= set(data["items"][0])

            res = await _history(db, u, layer="routing")
            assert [i["id"] for i in res["data"]["items"]] == ["d", "a"]
            res = await _history(db, u, limit=2)
            assert res["data"]["total"] == 2
            assert [i["id"] for i in res["data"]["items"]] == ["d", "c"]
            bad = await _history(db, u, layer="nope")
            assert bad["code"] == 400
        await engine.dispose()
    run(_run())


def test_history_parse_json_survives_bad_text():
    async def _run():
        engine, maker = await _setup()
        async with maker() as db:
            db.add(_make_user("u1"))
            r = EvaluationRun(id="j1", layer="e2e", mode="dry", status="success",
                              summary_json="not-json", failures_json="not-json",
                              duration_ms=5, created_at=datetime(2026, 9, 6, 8, 0, 0))
            db.add(r)
            await db.commit()
        async with maker() as db:
            u = await db.get(User, "u1")
            res = await _report(db, u, run_id="j1")
            assert res["code"] == 0
            assert res["data"]["runs"][0]["summary"] == {}
            assert res["data"]["runs"][0]["failures"] == []
        await engine.dispose()
    run(_run())
