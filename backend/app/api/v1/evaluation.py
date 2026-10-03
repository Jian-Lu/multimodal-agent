"""评估系统端点 — /api/v1/eval/*

所属层级: API / v1 / Evaluation

Phase 17: GET  /metrics           —— Layer 1 实时性能指标
Phase 18: POST /run (layer=routing)—— Layer 2 路由准确性评估 (默认 live, dry 走桩)
Phase 19: POST /run (layer=quality)—— Layer 3 输出质量评估 (LLM Judge, dry 满分桩)
Phase 20: POST /run (layer=e2e)   —— Layer 4 E2E 场景评估 (整图运行, dry 合成 trace)
Phase 21: GET  /report            —— 读 evaluation_runs: 默认各层最新聚合, run_id 单查; format=json|text|html
          GET  /report/history    —— 最近运行列表 (layer/limit 过滤)

最终评估 API 收紧时再叠加 require_admin 依赖 (当前按产品决策仅要求登录态)。
"""
import importlib
import json
import logging
import time

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse, PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.config import settings
from app.core.response import fail, ok
from app.evaluation.metrics_collector import get_metrics_collector
from app.evaluation.report_generator import digest_run, render_html, render_report_json, render_text
from app.models import EvaluationRun, User

# layer -> (引擎模块, golden 加载函数, 执行函数)
EVAL_ENGINES: dict[str, tuple[str, str, str]] = {
    "routing": ("app.evaluation.test_routing", "load_golden", "run_routing_eval"),
    "quality": ("app.evaluation.test_output_quality", "load_output_golden", "run_quality_eval"),
    "e2e": ("app.evaluation.test_e2e", "load_e2e_scenarios", "run_e2e_eval"),
}

logger = logging.getLogger("api.evaluation")

router = APIRouter(prefix="/eval", tags=["evaluation"])


@router.get("/metrics")
async def get_metrics(
    window_s: float | None = Query(
        default=None, description="统计窗口(秒), 缺省用 EVAL_METRICS_WINDOW_S"
    ),
    kinds: str | None = Query(
        default=None,
        description="逗号分隔的指标种类过滤, 如 hook_latency,router_latency",
    ),
    user: User = Depends(get_current_user),
) -> dict:
    """Layer 1 实时性能指标 (collector 内存快照)。"""
    win = window_s if window_s is not None else float(settings.EVAL_METRICS_WINDOW_S)
    kind_list = [k.strip() for k in kinds.split(",") if k.strip()] if kinds else None
    return ok(get_metrics_collector().snapshot(window_s=win, kinds=kind_list))


@router.post("/run")
async def run_evaluation(
    layer: str = Query(default="routing", description="routing | quality | e2e"),
    mode: str = Query(default="live", description="live(真实模型) | dry(关键字桩, 零 LLM)"),
    limit: int | None = Query(default=None, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """触发一次评估并持久化到 evaluation_runs (routing|quality)。"""
    mode = mode if mode in ("live", "dry") else "live"
    if layer not in EVAL_ENGINES:
        return fail(400, f"layer={layer} 尚未实现 (可选 {sorted(EVAL_ENGINES)}; e2e 后续阶段)")

    # lazy import: 避免在 API 模块加载期拖入 supervisor/LLM 链路
    mod_name, load_fn, run_fn = EVAL_ENGINES[layer]
    mod = importlib.import_module(mod_name)
    loader, runner = getattr(mod, load_fn), getattr(mod, run_fn)

    t0 = time.perf_counter()
    try:
        result = await runner(loader(), mode=mode, limit=limit)
    except Exception as e:  # noqa: BLE001 — 评估失败返回错误而非 500 崩溃
        logger.exception("评估失败 (layer=%s): %s", layer, e)
        return fail(500, f"{layer} 评估失败: {e}")

    duration_ms = round((time.perf_counter() - t0) * 1000)
    summary = {k: v for k, v in result.items() if k not in ("failures",)}
    summary["duration_ms"] = duration_ms
    run = EvaluationRun(
        layer=layer,
        mode=mode,
        status="success",
        summary_json=json.dumps(summary, ensure_ascii=False),
        failures_json=json.dumps(result.get("failures", []), ensure_ascii=False),
        duration_ms=duration_ms,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    result["run_id"] = run.id
    result["duration_ms"] = duration_ms
    return ok(result)


# ---------- Phase 21: 报告 / 历史 ----------
REPORT_FORMATS = ("json", "text", "html")


def _row_to_run(row: EvaluationRun) -> dict:
    """EvaluationRun 行 -> report_generator 的纯 run dict (两列 JSON 容错解析)。"""
    def _loads(raw: str, default):
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return default

    summary = _loads(row.summary_json or "{}", {})
    failures = _loads(row.failures_json or "[]", [])
    if not isinstance(summary, dict):
        summary = {}
    if not isinstance(failures, list):
        failures = []
    return {
        "run_id": row.id,
        "layer": row.layer,
        "mode": row.mode,
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "duration_ms": row.duration_ms,
        "summary": summary,
        "failures": failures,
    }


async def _latest_run_per_layer(db: AsyncSession, layers) -> dict[str, EvaluationRun]:
    """每层取 created_at 最新一条; 该层无记录则不出现。"""
    latest: dict[str, EvaluationRun] = {}
    for layer in layers:
        row = (await db.scalars(
            select(EvaluationRun)
            .where(EvaluationRun.layer == layer)
            .order_by(EvaluationRun.created_at.desc())
            .limit(1)
        )).first()
        if row is not None:
            latest[layer] = row
    return latest


@router.get("/report")
async def get_report(
    run_id: str | None = Query(default=None, description="精确查某次 run; 缺省返回各层最新聚合"),
    format: str = Query(default="json", description="json(信封) | text | html(原文)"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """读 evaluation_runs 生成报告: 默认 = routing/quality/e2e 各层最新聚合, 或 ?run_id 单查。"""
    fmt = format if format in REPORT_FORMATS else None
    if fmt is None:
        return fail(400, f"format={format} 不支持 (可选 {list(REPORT_FORMATS)})")

    if run_id:
        row = (await db.scalars(
            select(EvaluationRun).where(EvaluationRun.id == run_id)
        )).first()
        if row is None:
            return fail(404, f"run_id={run_id} 不存在")
        runs, report_type = [_row_to_run(row)], "single"
    else:
        latest = await _latest_run_per_layer(db, EVAL_ENGINES)
        runs = [_row_to_run(r) for r in latest.values()]
        report_type = "aggregate"

    if fmt == "json":
        return ok(render_report_json(runs, report_type=report_type))
    if fmt == "text":
        return PlainTextResponse(render_text(runs), media_type="text/plain; charset=utf-8")
    return HTMLResponse(render_html(runs))


@router.get("/report/history")
async def get_report_history(
    layer: str | None = Query(default=None, description="按层过滤 (routing|quality|e2e)"),
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """最近运行列表 (按 created_at 降序); 轻量 items(仅 digest 字段, 不含大 summary)。"""
    if layer is not None and layer not in EVAL_ENGINES:
        return fail(400, f"layer={layer} 未知 (可选 {sorted(EVAL_ENGINES)})")

    stmt = select(EvaluationRun).order_by(EvaluationRun.created_at.desc()).limit(limit)
    if layer is not None:
        stmt = stmt.where(EvaluationRun.layer == layer)
    rows = (await db.scalars(stmt)).all()

    items = []
    for r in rows:
        d = digest_run(_row_to_run(r))
        items.append({
            "id": r.id,
            "layer": r.layer,
            "mode": r.mode,
            "status": r.status,
            "duration_ms": r.duration_ms,
            "created_at": d["created_at"],
            "verdict": d["verdict"],
            "score": d["score"],
            "score_label": d["score_label"],
            "failures": d["failures"],
            "total": d["total"],
        })
    return ok({"items": items, "total": len(items), "layer": layer, "limit": limit})
