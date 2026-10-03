"""集成测试 — 多跳链路(搜索→报告) + 端到端 + 错误降级。"""
import asyncio
from unittest.mock import patch

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver

from app.agents.web_search_agent import WebSearchAgent


def run(coro):
    return asyncio.run(coro)


class FakeProvider:
    def __init__(self, results=None, fail=False):
        self.results = results or []
        self.fail = fail

    async def search(self, query, max_results=5):
        if self.fail:
            raise RuntimeError("search down")
        return self.results


class FakeLLM:
    def __init__(self, response="ok"):
        self.response = response

    async def astream(self, messages, **kwargs):
        yield type("Chunk", (), {"content": self.response})()


class CapturingLLM(FakeLLM):
    def __init__(self, response="ok"):
        super().__init__(response)
        self.messages = None

    async def astream(self, messages, **kwargs):
        self.messages = messages
        yield type("Chunk", (), {"content": self.response})()


def test_web_search_report_intent():
    provider = FakeProvider(results=[{"title": "T", "url": "http://x", "snippet": "s"}])
    agent = WebSearchAgent(provider=provider, llm=FakeLLM("摘要"))
    r1 = run(agent.run({"messages": [HumanMessage(content="帮我搜一下2024年AI趋势并写成报告")]}))
    assert r1["next_agent"] == "writer"
    r2 = run(agent.run({"messages": [HumanMessage(content="帮我搜一下2024年AI趋势")]}))
    assert r2["next_agent"] == "finish"


def test_writer_uses_search_results():
    from app.agents.writer import WriterAgent

    llm = CapturingLLM("报告内容")
    with patch("app.agents.writer.get_llm_by_intent", return_value=llm):
        agent = WriterAgent()
        result = run(
            agent.run(
                {
                    "messages": [HumanMessage(content="写报告")],
                    "search_results": {
                        "query": "AI趋势",
                        "summary": "搜索摘要内容",
                        "results": [{"title": "T", "url": "http://x"}],
                    },
                }
            )
        )
    prompt_text = " ".join(str(m.content) for m in llm.messages)
    assert "搜索摘要内容" in prompt_text
    assert result["final_answer"] == "报告内容"


def test_e2e_graph_search_to_report():
    from app.harness.graph import build_graph
    from app.skills import load_builtin_skills

    load_builtin_skills()

    provider = FakeProvider(
        results=[{"title": "AI趋势", "url": "http://example.com", "snippet": "2024 AI 趋势"}]
    )
    summary_llm = FakeLLM("搜索摘要")
    report_llm = FakeLLM("报告正文(含来源引用)")

    with patch("app.agents.web_search_agent.get_search_provider", return_value=provider), patch(
        "app.agents.web_search_agent.get_llm_by_intent", return_value=summary_llm
    ), patch("app.agents.writer.get_llm_by_intent", return_value=report_llm):
        graph = build_graph(MemorySaver())
        result = run(
            graph.ainvoke(
                {"messages": [HumanMessage(content="帮我搜一下2024年AI趋势并写成报告")]},
                config={"configurable": {"thread_id": "e2e"}, "recursion_limit": 10},
            )
        )
        assert "报告正文" in result["final_answer"]
        assert result["search_results"]["summary"] == "搜索摘要"


def test_error_fallback_on_search_down():
    agent = WebSearchAgent(provider=FakeProvider(fail=True), llm=FakeLLM("摘要"))
    result = run(agent.run({"messages": [HumanMessage(content="帮我搜一下xxx")]}))
    assert "不可用" in result["final_answer"] or "重试" in result["final_answer"]
