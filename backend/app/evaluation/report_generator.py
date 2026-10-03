"""Evaluation 层 — 报告生成器 (text ✅⚠️❌ / JSON / HTML)。

所属层级: Evaluation / Phase 21

输入是 API 组装好的 **纯 run dict**(本模块绝不引 ORM/业务):
    {"run_id","layer","mode","status","created_at"(iso),"duration_ms",
     "summary":{...摘要 JSON...}, "failures":[...JSON...]}
- digest_run: 抽出跨层统一展示的最小子集(前端/历史只靠它)。
- render_report_json / render_text / render_html: 三种渲染, 全部纯函数, 可离线单测。

量纲(以各引擎持久化 summary 实测定标):
    routing.accuracy 0-1      -> ×100  (label 路由准确率)
    quality agents[].overall_avg 1-5  -> ÷5×100 (label 输出质量, Judge 均分)
    e2e    .pass_rate 0-1     -> ×100  (label E2E 通过率)
"""
from html import escape

VERDICT_SYMBOL = {"ok": "✅", "warn": "⚠", "fail": "❌"}
DEFAULT_EXPECTED_LAYERS = ("routing", "quality", "e2e")
LAYER_LABELS = {"routing": "路由准确性", "quality": "输出质量", "e2e": "E2E 场景"}


def _clamp100(x: float) -> float:
    return round(max(0.0, min(100.0, x)), 1)


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _verdict(status: str, failures: list) -> str:
    """ok: 成功且无失败; warn: 成功但有失败; fail: 状态非 success(引擎异常)。"""
    if status != "success":
        return "fail"
    return "ok" if not failures else "warn"


def _layer_score(summary: dict, layer: str):
    """按层从 summary 抽归一化 0-100 分数 + 标签; 数据缺失返回 (None, None)。"""
    if layer == "routing":
        acc = summary.get("accuracy")
        if _is_num(acc):
            return _clamp100(float(acc) * 100), "路由准确率"
    elif layer == "quality":
        agents = summary.get("agents")
        if isinstance(agents, dict) and agents:
            scores = [a["overall_avg"] for a in agents.values()
                      if isinstance(a, dict) and _is_num(a.get("overall_avg"))]
            if scores:
                return _clamp100(sum(scores) / len(scores) / 5 * 100), "输出质量"
    elif layer == "e2e":
        pr = summary.get("pass_rate")
        if _is_num(pr):
            return _clamp100(float(pr) * 100), "E2E 通过率"
    return None, None


def digest_run(run: dict) -> dict:
    """跨层统一的最小展示集。summary 缺失键一律容错。"""
    summary = run.get("summary") or {}
    failures = run.get("failures") or []
    if not isinstance(failures, list):
        failures = []
    layer = run.get("layer", "")
    score, score_label = _layer_score(summary, layer)
    verdict = _verdict(str(run.get("status", "success")), failures)
    total = summary.get("total")
    return {
        "run_id": run.get("run_id"),
        "layer": layer,
        "layer_label": LAYER_LABELS.get(layer, layer),
        "mode": run.get("mode"),
        "status": run.get("status", "success"),
        "verdict": verdict,
        "score": score,
        "score_label": score_label,
        "failures": len(failures),
        "total": total if _is_num(total) else None,
        "duration_ms": run.get("duration_ms"),
        "created_at": run.get("created_at"),
    }


# ---------- JSON ----------
def render_report_json(runs: list[dict], report_type: str = "aggregate",
                       expected_layers=DEFAULT_EXPECTED_LAYERS) -> dict:
    """机器结构: layers 放各层 digest(缺失 null), runs 放完整 run dict。"""
    present = {r.get("layer") for r in runs}
    layers: dict[str, dict] = {}
    for layer in expected_layers:
        row = next((r for r in runs if r.get("layer") == layer), None)
        if row is not None:
            layers[layer] = digest_run(row)
    return {
        "type": report_type,
        "layers": layers,
        "missing": [l for l in expected_layers if l not in present],
        "runs": runs,
    }


# ---------- text ----------
_FAILURE_MINOR_KEYS = ("expected", "actual", "got", "judge", "overall", "category")


def _failure_lines(f: dict, prefix: str = "      ") -> list[str]:
    """按各层失败条目的异构字段尽力格式化: reason/detail/error/comment + 次要键 + checks/excerpt。"""
    lines: list[str] = []
    reason = (f.get("reason") or f.get("detail") or f.get("error")
              or f.get("comment") or "").strip()
    label = f.get("id") or f.get("case_id") or f.get("agent") or "?"
    lines.append(f"  ⚠ {label}: {str(reason)[:200] if reason else '—'}")
    for k in _FAILURE_MINOR_KEYS:
        v = f.get(k)
        if v is not None and v != "" and str(v) not in str(reason):
            lines.append(f"{prefix}- {k}: {str(v)[:120]}")
    if f.get("checks"):
        for c in f["checks"]:
            if isinstance(c, dict):
                lines.append(f"{prefix}- {c.get('type')}: {str(c.get('detail', ''))[:120]}")
    if f.get("error"):
        lines.append(f"{prefix}- error: {str(f['error'])[:200]}")
    excerpt = f.get("output_excerpt")
    if excerpt:
        lines.append(f"{prefix}- excerpt: {str(excerpt)[:200]}")
    return lines


def render_text(runs: list[dict]) -> str:
    if not runs:
        return "[评估报告] (evaluation_runs 无记录)"
    lines = ["[评估报告] 共 %d 条运行" % len(runs)]
    for r in runs:
        d = digest_run(r)
        sym = VERDICT_SYMBOL[d["verdict"]]
        score = f"{d['score']}%" if d["score"] is not None else "-"
        lines.append(
            f"{sym} {d['layer_label']} score={score} mode={d['mode']} "
            f"status={d['status']} failures={d['failures']} "
            f"duration={d['duration_ms']}ms @{d['created_at']} run={d['run_id']}"
        )
        for f in r.get("failures") or []:
            if isinstance(f, dict):
                lines.extend(_failure_lines(f))
    return "\n".join(lines)


# ---------- html ----------
def _esc(v) -> str:
    return escape("" if v is None else str(v))


def render_html(runs: list[dict]) -> str:
    """自包含单文件 HTML(内联 CSS)。所有回显字段先 html.escape。"""
    cards: list[str] = []
    for r in runs:
        d = digest_run(r)
        sym = VERDICT_SYMBOL[d["verdict"]]
        bar = ""
        if d["score"] is not None:
            bar = (f'<div class="bar"><div class="bar-fill" style="width:{d["score"]:.1f}%">'
                   f'</div></div>')
        fails = r.get("failures") or []
        fail_html = ""
        if fails:
            items = []
            for f in fails:
                if not isinstance(f, dict):
                    continue
                reason = _esc(f.get("reason") or f.get("detail") or f.get("error") or "")
                label = _esc(f.get("id") or f.get("case_id") or f.get("agent") or "?")
                checks = ""
                if f.get("checks"):
                    cs = "".join(
                        f"<li>{_esc(c.get('type'))}: {_esc(c.get('detail', ''))}</li>"
                        for c in f["checks"] if isinstance(c, dict)
                    )
                    checks = f"<ul class=\"checks\">{cs}</ul>"
                error = ""
                if f.get("error"):
                    error = f'<div class="err">error: {_esc(f["error"])}</div>'
                excerpt = f.get("output_excerpt")
                ex = f'<div class="ex">excerpt: {_esc(str(excerpt)[:200])}</div>' if excerpt else ""
                items.append(f'<li><b>{label}</b> — {reason}{checks}{error}{ex}</li>')
            fail_html = (f'<details><summary>失败明细 ({len(fails)})</summary>'
                         f'<ul class="failures">{"".join(items)}</ul></details>')
        meta = (f'{_esc(d["mode"])} · {sym} {_esc(d["status"])} · '
                f'失败 {d["failures"]} · {_esc(d["duration_ms"])}ms · '
                f'{_esc(d["created_at"])}')
        score_txt = f'{d["score"]:.1f}%' if d["score"] is not None else "-"
        cards.append(
            f'<section class="card"><div class="card-head"><h2>{sym} {_esc(d["layer_label"])}'
            f'</h2><span class="badge {d["verdict"]}">{_esc(score_txt)}</span></div>'
            f'{bar}<div class="meta">{meta}</div><div class="sub">run_id={_esc(d["run_id"])}'
            f'</div>{fail_html}</section>'
        )
    body = "".join(cards) if cards else "<p class=\"empty\">evaluation_runs 无记录</p>"
    return (
        "<!DOCTYPE html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<title>评估报告</title><style>"
        "body{font-family:system-ui,-apple-system,'Segoe UI',sans-serif;margin:24px auto;"
        "max-width:760px;padding:0 16px;color:#1f2937;background:#f8fafc}"
        ".card{background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:16px 18px;"
        "margin-bottom:14px;box-shadow:0 1px 2px rgba(0,0,0,.04)}"
        ".card-head{display:flex;justify-content:space-between;align-items:center;gap:12px}"
        "h2{margin:0;font-size:16px}.badge{font-size:14px;font-weight:600;padding:2px 10px;"
        "border-radius:999px}.badge.ok{background:#dcfce7;color:#166534}"
        ".badge.warn{background:#fef3c7;color:#92400e}.badge.fail{background:#fee2e2;color:#991b1b}"
        ".bar{height:8px;background:#e5e7eb;border-radius:999px;overflow:hidden;margin:10px 0 8px}"
        ".bar-fill{height:100%;background:#3b82f6;border-radius:999px}"
        ".meta{color:#6b7280;font-size:12.5px;margin-top:2px}.sub{color:#9ca3af;font-size:11px;"
        "margin-top:2px;word-break:break-all}"
        "details{margin-top:8px}summary{cursor:pointer;font-size:13px;color:#4b5563}"
        "ul.failures{font-size:12.5px;color:#374151;margin:8px 0 0;padding-left:18px}"
        "ul.failures li{margin-bottom:6px}.checks{margin:4px 0 0;color:#6b7280}"
        ".err{color:#b91c1c}.ex{color:#6b7280;font-style:italic}"
        ".empty{color:#6b7280}</style></head><body>" + body + "</body></html>"
    )
