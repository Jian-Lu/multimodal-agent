"""极简 MCP 集成 — RAG 绑定 GitHub 工具的测试。

覆盖: 无工具时纯 RAG 优雅降级、工具调用流、工具失败降级、
Supervisor github 路由、图级端到端(查 github issue → rag → 工具)。
"""
import asyncio

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool


def run(coro):
    return asyncio.run(coro)


class FakeStore:
    def __init__(self, docs=None):
        self.docs = docs or []

    def query(self, text, k=None):
        return self.docs


class FakeToolLLM:
    """支持 astream(无工具纯问答) + bind_tools/ainvoke(工具循环)。"""

    def __init__(self, responses=None, stream_response="基于知识库的回答"):
        self.responses = list(responses or [])
        self.stream_response = stream_response
        self.bound_tools = None
        self.calls = []

    def bind_tools(self, tools):
        self.bound_tools = tools
        return self

    async def ainvoke(self, messages, **kwargs):
        self.calls.append(messages)
        return self.responses.pop(0)

    async def astream(self, messages, **kwargs):
        yield type("Chunk", (), {"content": self.stream_response})()


def make_issues_tool(fail=False):
    """构造一个真实的 StructuredTool(镜像 mcp_github_search_issues), 记录调用次数。"""
    state = {"n": 0}

    async def _run(owner: str, repo: str) -> str:
        state["n"] += 1
        if fail:
            raise RuntimeError("MCP server 断开")
        return f"[{owner}/{repo}] 共 5 个 issue: #1 #2 #3 #4 #5"

    def _sync(owner: str = "", repo: str = "") -> str:
        return f"[{owner}/{repo}] 0 issues"

    tool = StructuredTool.from_function(
        func=_sync,
        coroutine=_run,
        name="mcp_github_search_issues",
        description="查询 GitHub 仓库的 issue 列表",
    )
    return tool, state


def _tool_call(**overrides):
    call = {
        "name": "mcp_github_search_issues",
        "args": {"owner": "langchain-ai", "repo": "langchain"},
        "id": "call_1",
        "type": "tool_call",
    }
    call.update(overrides)
    return call


def _rag_agent(llm, tools, monkeypatch, docs=None):
    from app.agents.rag import RagAgent

    monkeypatch.setattr("app.agents.rag.get_chroma_store", lambda: FakeStore(docs=docs))
    monkeypatch.setattr("app.agents.rag.get_github_mcp_tools", lambda: tools)
    return RagAgent(llm=llm)


def test_no_tools_graceful(monkeypatch):
    """未连接 MCP -> 空工具列表 -> 纯 RAG 问答(不触发 bind_tools)。"""
    agent = _rag_agent(FakeToolLLM(stream_response="知识库回答内容"), [], monkeypatch, docs=["知识块"])
    result = run(agent.run({"messages": [HumanMessage(content="什么是 RAG?")]}))
    assert "知识库回答内容" in result["final_answer"]
    assert result["next_agent"] == "finish"


def test_tool_call_flow(monkeypatch):
    """LLM 请求工具 -> 工具执行 -> ToolMessage 回填 -> 最终答案。"""
    tool, state = make_issues_tool()
    llm = FakeToolLLM(
        responses=[
            AIMessage(content="", tool_calls=[_tool_call()]),
            AIMessage(content="共找到 5 个 issue, 结论..."),
        ]
    )
    agent = _rag_agent(llm, [tool], monkeypatch)
    result = run(agent.run({"messages": [HumanMessage(content="查一下 langchain-ai/langchain 最近的 5 个 issue")]}))
    assert "共找到 5 个 issue" in result["final_answer"]
    assert state["n"] == 1
    assert len(llm.calls) == 2  # 两轮: 工具调用 + 最终回答
    second_round = llm.calls[1]
    assert any(isinstance(m, ToolMessage) for m in second_round)


def test_tool_failure_degrades(monkeypatch):
    """工具抛错 -> ToolMessage 含失败信息 -> 第二轮 LLM 兜底, 不崩溃。"""
    tool, _ = make_issues_tool(fail=True)
    llm = FakeToolLLM(
        responses=[
            AIMessage(content="", tool_calls=[_tool_call()]),
            AIMessage(content="GitHub 服务不可用, 基于通用知识回答: ..."),
        ]
    )
    agent = _rag_agent(llm, [tool], monkeypatch)
    result = run(agent.run({"messages": [HumanMessage(content="查一下 langchain-ai/langchain 的 issue")]}))
    assert "GitHub 服务不可用" in result["final_answer"]
    tm = [m for m in llm.calls[1] if isinstance(m, ToolMessage)]
    assert tm and "工具调用失败" in tm[0].content


def test_supervisor_github_routing():
    from app.harness.supervisor import supervisor_node

    r = supervisor_node({"messages": [HumanMessage(content="查一下 langchain-ai/langchain 最近的 5 个 issue")]})
    assert r["next_agent"] == "rag"  # github 关键词优先于"查一下"的搜索路由
    r2 = supervisor_node({"messages": [HumanMessage(content="搜索 github 趋势")]})
    assert r2["next_agent"] == "rag"
    r3 = supervisor_node({"messages": [HumanMessage(content="介绍 langchain 仓库的 star 数")]})
    assert r3["next_agent"] == "rag"  # 命中"仓库"
    r4 = supervisor_node({"messages": [HumanMessage(content="写个 python 脚本算斐波那契")]})
    assert r4["next_agent"] == "coder"  # 代码意图不受影响


def test_e2e_graph_github_query(monkeypatch):
    from unittest.mock import patch

    from langgraph.checkpoint.memory import MemorySaver

    from app.harness.graph import build_graph
    from app.skills import load_builtin_skills

    load_builtin_skills()
    tool, _ = make_issues_tool()
    llm = FakeToolLLM(
        responses=[
            AIMessage(content="", tool_calls=[_tool_call()]),
            AIMessage(content="langchain 最近 5 个 issue 分别是: #1 #2 #3 #4 #5"),
        ]
    )
    monkeypatch.setattr("app.agents.rag.get_chroma_store", lambda: FakeStore())
    monkeypatch.setattr("app.agents.rag.get_github_mcp_tools", lambda: [tool])
    with patch("app.agents.rag.get_llm_by_intent", return_value=llm):
        graph = build_graph(MemorySaver())
        result = run(
            graph.ainvoke(
                {"messages": [HumanMessage(content="查一下 langchain-ai/langchain 最近的 5 个 issue")]},
                config={"configurable": {"thread_id": "gh"}, "recursion_limit": 10},
            )
        )
    assert "langchain 最近 5 个 issue" in result["final_answer"]
