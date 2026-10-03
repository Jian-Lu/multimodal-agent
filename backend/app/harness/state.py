"""Harness 层 — AgentState 共享状态定义 + RoutingDecision 路由决策模型。

所属层级: Harness
"""
from typing import Annotated, Literal, Optional, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field


class RoutingDecision(BaseModel):
    """Supervisor LLM 结构化输出 — 一次路由决策。"""

    next_agent: Literal["rag", "coder", "web_search", "writer", "mcp_github", "finish"]
    skill_name: Optional[str] = None      # 匹配到的 Skill(可选)
    mcp_tool_hint: Optional[str] = None   # 建议使用的 MCP 工具(仅日志)
    reasoning: str = Field(description="简短的路由理由, 用于日志")
    confidence: float = Field(ge=0, le=1)


class AgentState(TypedDict, total=False):
    """多智能体图共享状态。"""

    messages: Annotated[list[BaseMessage], add_messages]  # 对话历史(累加)
    next_agent: str            # vision | rag | coder | writer | web_search | finish
    iteration_count: int       # 递归计数(安全阀, ≤10)
    mode: str                  # chat | document
    images: list[str]          # base64 data-url 列表
    final_answer: str          # 最终回答
    code: str                  # Coder 产出的代码
    code_result: str           # Sandbox 执行结果
    token_budget_exceeded: bool  # Hook 标记: 是否超 token 预算
    search_results: dict | None  # Web Search 结构化结果 {query, results, summary}
    skill: str  # 命中的技能名(可选)
