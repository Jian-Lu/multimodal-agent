"""Agent 层 — Web Search Agent 单元测试。

所属层级: Agent
"""
import asyncio

from langchain_core.messages import HumanMessage

from app.agents.web_search_agent import WebSearchAgent, extract_query


def run(coro):
    return asyncio.run(coro)


class FakeProvider:
    def __init__(self, results=None, fail=False):
        self.results = results or []
        self.fail = fail
        self.calls = 0

    async def search(self, query, max_results=5):
        self.calls += 1
        if self.fail:
            raise RuntimeError("search down")
        return self.results


class FakeLLM:
    def __init__(self, response="这是摘要"):
        self.response = response

    async def astream(self, messages, **kwargs):
        yield type("Chunk", (), {"content": self.response})()


def test_extract_query():
    assert extract_query("搜索一下2024年AI趋势") == "2024年AI趋势"
    assert extract_query("查一下 天气") == "天气"
    assert extract_query("直接问题") == "直接问题"


def test_empty_results_anti_hallucination():
    agent = WebSearchAgent(provider=FakeProvider(results=[]), llm=FakeLLM())
    result = run(agent.run({"messages": [HumanMessage(content="搜索xxx")]}))
    assert "未找到相关信息" in result["final_answer"]
    assert "search_results" not in result


def test_summary_with_citations():
    provider = FakeProvider(
        results=[{"title": "标题", "url": "http://example.com", "snippet": "片段"}]
    )
    agent = WebSearchAgent(provider=provider, llm=FakeLLM("这是摘要内容"))
    result = run(agent.run({"messages": [HumanMessage(content="搜索xxx")]}))
    assert "这是摘要内容" in result["final_answer"]
    assert "http://example.com" in result["final_answer"]
    assert result["search_results"]["summary"] == "这是摘要内容"


def test_cache():
    provider = FakeProvider(results=[{"title": "T", "url": "http://x", "snippet": "s"}])
    agent = WebSearchAgent(provider=provider, llm=FakeLLM())
    run(agent.run({"messages": [HumanMessage(content="搜索缓存测试")]}))
    run(agent.run({"messages": [HumanMessage(content="搜索缓存测试")]}))
    assert provider.calls == 1  # 第二次命中缓存


def test_search_failure():
    agent = WebSearchAgent(provider=FakeProvider(fail=True), llm=FakeLLM())
    result = run(agent.run({"messages": [HumanMessage(content="搜索xxx")]}))
    assert "不可用" in result["final_answer"] or "重试" in result["final_answer"]
