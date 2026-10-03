"""Harness 层 — Supervisor 节点: 规则前置 + LLM 意图识别路由。

所属层级: Harness

路由决策分层:
1. 规则前置(不调 LLM, 硬性约束): 迭代超限 → finish; 有图片 → vision;
   document 模式 → writer。
2. LLM 意图识别(仅文本): 用路由专用模型 get_llm_by_intent("routing") 的
   structured output 得到 RoutingDecision, 再解析为图节点:
   - skill_name 命中且 enabled → 用 skill.target_agent 并注入渲染后的 prompt
   - mcp_github(LLM 语义值) → 映射为图节点 rag(github 工具绑定在 RAG 的 ReAct 循环)
   - confidence < 0.6 / 非法节点 / LLM 异常或超时 → fallback rag

iteration_count 仍作为原有图级安全阀(每次 supervisor 访问 +1); LLM 路由调用
本身不额外计入迭代预算。
"""
import asyncio
import logging
import time

from langchain_core.messages import HumanMessage, SystemMessage

from app.evaluation.metrics_collector import get_metrics_collector
from app.harness.state import AgentState, RoutingDecision
from app.llm.factory import get_llm_by_intent
from app.mcp_sdk.manager import get_mcp_manager
from app.skills import get_skill_registry

logger = logging.getLogger("harness.supervisor")

MAX_ITERATIONS = 10
ROUTING_TIMEOUT = 3.0          # 秒; 超时 → fallback rag
ROUTING_CONF_THRESHOLD = 0.6   # confidence 低于该值 → fallback rag
LEGAL_AGENTS = ("rag", "vision", "coder", "writer", "web_search", "finish")
# LLM 语义节点 → 图节点(极简 MCP 集成: 无独立 mcp_github 节点, 工具绑定在 RAG)
DECISION_TO_NODE: dict[str, str] = {"mcp_github": "rag"}


def _record_supervisor_latency(latency_ms: float, outcome: str = "ok", **tags) -> None:
    """记录 LLM 路由决策延迟 (supervisor_latency)。采集异常不影响路由。"""
    try:
        get_metrics_collector().record(
            "supervisor_latency", value=latency_ms, outcome=outcome, **tags
        )
    except Exception:  # noqa: BLE001
        pass

_NO_MCP = "(无可用 MCP 工具)"

# Skills / MCP 工具摘要缓存(60s), 签名键控: 内容变化自动失效(测试安全)
_CONTEXT_TTL = 60.0
_context_cache: dict = {"ts": 0.0, "sig": None, "skills": "", "mcp": ""}

SYSTEM_PROMPT = """你是一个任务路由器。根据用户消息，选择最合适的处理节点。

可用节点：
- rag: 知识库检索、通用问答、GitHub 相关问题(当无 MCP 工具时)
- coder: 代码生成、代码修改、编程问题
- web_search: 实时信息检索、新闻、最新事件
- writer: 报告、文档、Markdown 生成
{mcp_github_line}- finish: 任务完成或无法处理

可用 Skills(优先级最高, 若匹配则填 skill_name 并选其对应 agent):
{skills_description}

可用 MCP 工具:
{mcp_tools_summary}

规则：
1. 如果用户意图明确匹配某个 Skill, 优先选择该 Skill 对应的 agent
2. 如果涉及 GitHub 操作且有 MCP 工具可用, 选择 mcp_github
3. 不确定时选择 rag 作为默认兜底
4. confidence < 0.6 时选择 rag 兜底"""


def _last_text(state: AgentState) -> str:
    """取最后一条消息文本(原文, 供 LLM 语义理解)。"""
    messages = state.get("messages") or []
    if not messages:
        return ""
    content = messages[-1].content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            p.get("text", "") if isinstance(p, dict) else str(p) for p in content
        )
    return str(content)


def _routing_context() -> tuple[str, str]:
    """构建 Skills 描述 + MCP 工具摘要(60s TTL 缓存, 签名变化自动刷新)。"""
    now = time.monotonic()
    skills = get_skill_registry().list(enabled_only=True)
    tools = get_mcp_manager().get_all_tools()
    sig = (
        tuple((s.name, s.description or "") for s in skills),
        tuple((t.server_id, t.name) for t in tools),
    )
    if now - _context_cache["ts"] < _CONTEXT_TTL and _context_cache["sig"] == sig:
        return _context_cache["skills"], _context_cache["mcp"]

    skills_desc = "\n".join(f"- {n}: {d}" for n, d in sig[0]) or "(无可用 Skills)"
    mcp_summary = "\n".join(f"- {t.name}: {t.description or ''}" for t in tools[:20]) or _NO_MCP
    _context_cache.update(ts=now, sig=sig, skills=skills_desc, mcp=mcp_summary)
    return skills_desc, mcp_summary


def _resolve_decision(decision: RoutingDecision, it: int, latency_ms: float) -> dict:
    """把 LLM 的 RoutingDecision 解析为图节点 next_agent(含 skill/兜底处理)。"""
    agent = decision.next_agent
    skill = None
    if decision.skill_name:
        skill = get_skill_registry().get(decision.skill_name)
        if skill is not None and skill.enabled:
            agent = skill.target_agent

    agent = DECISION_TO_NODE.get(agent, agent)

    if decision.confidence < ROUTING_CONF_THRESHOLD:
        logger.warning(
            "[SUPERVISOR] confidence %.2f < %.2f, fallback rag",
            decision.confidence,
            ROUTING_CONF_THRESHOLD,
        )
        agent = "rag"
    if agent not in LEGAL_AGENTS:
        logger.warning("[SUPERVISOR] 非法节点 %s, fallback rag", agent)
        agent = "rag"

    result = {"next_agent": agent, "iteration_count": it}
    if skill is not None:
        result["skill"] = skill.name
        result["messages"] = [SystemMessage(content=get_skill_registry().render_prompt(skill, {}))]
    _record_supervisor_latency(
        latency_ms,
        next_agent=agent,
        decision=decision.next_agent,
        skill=(skill.name if skill is not None else (decision.skill_name or "")),
        confidence=round(decision.confidence, 3),
    )
    logger.info(
        "[SUPERVISOR] decision=%s skill=%s conf=%.2f latency=%.0fms",
        decision.next_agent,
        decision.skill_name or "-",
        decision.confidence,
        latency_ms,
    )
    return result


async def supervisor_node(state: AgentState) -> dict:
    """规则前置 + LLM 意图识别路由, 返回 {next_agent, iteration_count, ...}。"""
    it = state.get("iteration_count", 0) + 1
    if it > MAX_ITERATIONS:
        return {"next_agent": "finish", "iteration_count": it}
    if state.get("images"):
        return {"next_agent": "vision", "iteration_count": it}
    if state.get("mode") == "document":
        return {"next_agent": "writer", "iteration_count": it}

    text = _last_text(state)
    if not text:
        return {"next_agent": "rag", "iteration_count": it}

    t0 = time.perf_counter()
    try:
        skills_desc, mcp_summary = _routing_context()
        mcp_github_line = (
            "- mcp_github: GitHub 仓库操作(issue/PR/文件查询等, 有对应 MCP 工具时使用)\n"
            if mcp_summary != _NO_MCP
            else ""
        )
        prompt = [
            SystemMessage(
                content=SYSTEM_PROMPT.format(
                    mcp_github_line=mcp_github_line,
                    skills_description=skills_desc,
                    mcp_tools_summary=mcp_summary,
                )
            ),
            HumanMessage(content=text),
        ]
        # tag="routing": 该内部路由流会被 chat.py SSE 过滤, 不透出给用户
        structured = get_llm_by_intent("routing").with_structured_output(RoutingDecision)
        decision = await asyncio.wait_for(
            structured.ainvoke(prompt, config={"tags": ["routing"]}),
            timeout=ROUTING_TIMEOUT,
        )
    except Exception as e:  # noqa: BLE001 — 路由失败不阻塞主流程
        latency_ms = (time.perf_counter() - t0) * 1000
        logger.warning("[SUPERVISOR] LLM 路由失败, fallback rag: %s (%.0fms)", e, latency_ms)
        _record_supervisor_latency(latency_ms, outcome="fallback_rag", next_agent="rag")
        return {"next_agent": "rag", "iteration_count": it}

    latency_ms = (time.perf_counter() - t0) * 1000
    return _resolve_decision(decision, it, latency_ms)
