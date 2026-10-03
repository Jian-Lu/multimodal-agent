"""Agent 层 — Writer 专家 (结构化 Markdown 文档生成)。

所属层级: Agent
"""
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.agents.base import BaseAgent
from app.harness.state import AgentState
from app.llm.factory import get_llm_by_intent

WRITER_SYSTEM = (
    "你是一个专业的技术文档撰写者。根据用户主题生成结构化 Markdown 文档,"
    "必须包含以下元素:\n"
    "1. 多级标题(# / ## / ###)\n"
    "2. 无序/有序列表\n"
    "3. 表格(用 | 分隔)\n"
    "4. 代码块(带语言标注, 如 ```python)\n"
    "5. 至少一个 Mermaid 流程图(```mermaid ... ```)\n"
    "直接输出 Markdown 正文, 不要额外解释。"
)


class WriterAgent(BaseAgent):
    name = "writer"

    async def run(self, state: AgentState) -> dict:
        topic = ""
        if state.get("messages"):
            c = state["messages"][-1].content
            topic = c if isinstance(c, str) else str(c)

        search = state.get("search_results")
        if search:
            content = self._build_report_prompt(search)
        else:
            content = f"主题: {topic}"

        prompt = [SystemMessage(content=WRITER_SYSTEM), HumanMessage(content=content)]
        text = await self.astream_text(get_llm_by_intent("document"), prompt)

        return {
            "messages": [AIMessage(content=text)],
            "final_answer": text,
            "next_agent": "finish",
        }

    def _build_report_prompt(self, search: dict) -> str:
        """把搜索结果拼成报告素材。"""
        query = search.get("query", "")
        summary = search.get("summary", "")
        results = search.get("results", [])
        lines = ["请根据以下搜索结果撰写一份结构化报告。", f"查询主题: {query}", "", "搜索结果摘要:", summary, "", "来源:"]
        for r in results:
            lines.append(f"- {r.get('title', '')} ({r.get('url', '')})")
        return "\n".join(lines)
