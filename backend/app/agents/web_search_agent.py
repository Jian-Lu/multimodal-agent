"""Agent 层 — Web Search 专家 (联网检索 + 摘要 + 来源引用)。

所属层级: Agent

流程: 提取 query → 查缓存(5min TTL) → 搜索 → 防幻觉 → LLM 摘要(快速模型) → 格式化。
防幻觉: 结果为空/搜索失败时明确告知, 绝不调用 LLM 编造。
"""
import logging
import time

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.agents.base import BaseAgent
from app.config import settings
from app.harness.state import AgentState
from app.llm.factory import get_llm_by_intent
from app.tools.search import get_search_provider

logger = logging.getLogger("agent.web_search")

_SEARCH_TRIGGERS = ("搜索一下", "搜一下", "帮我搜索", "帮我搜", "搜索", "搜", "查一下", "帮我查")

_REPORT_KEYWORDS = ("报告", "写成", "总结成", "生成文档", "markdown")

SUMMARY_SYSTEM = (
    "你是一个搜索助手。根据给定的搜索结果, 用中文简洁总结回答用户的查询,"
    "并在关键信息处用 Markdown 链接标注来源。只依据提供的搜索结果, 不要编造。"
)


class TTLCache:
    """简单内存 TTL 缓存(避免引入 Redis/额外依赖)。"""

    def __init__(self, ttl: int = 300) -> None:
        self._ttl = ttl
        self._data: dict[str, tuple[object, float]] = {}

    def get(self, key: str):
        item = self._data.get(key)
        if item is None:
            return None
        value, ts = item
        if time.time() - ts < self._ttl:
            return value
        del self._data[key]
        return None

    def set(self, key: str, value: object) -> None:
        self._data[key] = (value, time.time())


def extract_query(text: str) -> str:
    """剥离搜索触发词, 提取真实查询。"""
    q = (text or "").strip()
    for t in _SEARCH_TRIGGERS:
        if q.startswith(t):
            q = q[len(t):].strip()
            break
    return q or (text or "").strip()


class WebSearchAgent(BaseAgent):
    name = "web_search"

    def __init__(self, provider=None, llm=None) -> None:
        # 依赖可注入(便于单元测试)
        self.provider = provider or get_search_provider()
        self._llm = llm
        self.cache = TTLCache(settings.SEARCH_CACHE_TTL)

    def _get_llm(self):
        return self._llm or get_llm_by_intent("search")

    async def run(self, state: AgentState) -> dict:
        text = ""
        if state.get("messages"):
            c = state["messages"][-1].content
            text = c if isinstance(c, str) else str(c)
        query = extract_query(text)

        if not query:
            return self._reply("未找到相关信息", None)

        # 查缓存
        cached = self.cache.get(query)
        if cached is not None:
            markdown = self._format_markdown(query, cached["summary"], cached["results"])
            return self._reply(markdown, cached)

        # 搜索
        try:
            results = await self.provider.search(query, max_results=settings.SEARCH_MAX_RESULTS)
        except Exception as e:  # noqa: BLE001
            logger.warning("WebSearch: 搜索失败 %s", e)
            return self._reply("搜索服务暂时不可用，请稍后重试。", None)

        # 防幻觉: 无结果不编造
        if not results:
            return self._reply("未找到相关信息", None)

        # LLM 摘要(快速模型)
        prompt = [
            SystemMessage(content=SUMMARY_SYSTEM),
            HumanMessage(content=self._summary_prompt(query, results)),
        ]
        summary = await self.astream_text(self._get_llm(), prompt)

        structured = {"query": query, "results": results, "summary": summary}
        self.cache.set(query, structured)

        markdown = self._format_markdown(query, summary, results)
        next_agent = "writer" if self._wants_report(text) else "finish"
        return self._reply(markdown, structured, next_agent)

    def _summary_prompt(self, query: str, results: list[dict]) -> str:
        lines = [f"查询: {query}", "", "搜索结果:"]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r['title']} - {r['url']}\n   {r['snippet']}")
        return "\n".join(lines)

    def _format_markdown(self, query: str, summary: str, results: list[dict]) -> str:
        lines = [f"**关于「{query}」的搜索结果**", "", summary]
        if results:
            lines += ["", "### 来源"]
            for r in results:
                lines.append(f"- [{r['title']}]({r['url']})")
        return "\n".join(lines)

    def _wants_report(self, text: str) -> bool:
        """判断消息是否要求「写成报告」, 是则链到 writer。"""
        t = (text or "").lower()
        return any(k in t for k in _REPORT_KEYWORDS)

    def _reply(self, markdown: str, structured: dict | None, next_agent: str = "finish") -> dict:
        result = {
            "messages": [AIMessage(content=markdown)],
            "final_answer": markdown,
            "next_agent": next_agent,
        }
        if structured is not None:
            result["search_results"] = structured
        return result
