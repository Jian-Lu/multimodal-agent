"""Agent 层 — RAG 专家 (ChromaDB 检索 + 生成)。

所属层级: Agent
"""
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.agents.base import BaseAgent
from app.harness.state import AgentState
from app.llm.factory import get_llm_by_intent
from app.mcp_sdk.github_client import get_github_mcp_tools
from app.memory.chroma import get_chroma_store

RAG_SYSTEM = (
    "你是一个基于知识库的问答助手。请优先依据提供的上下文回答问题;"
    "若上下文不足以回答, 可基于通用知识作答, 但需简要说明依据不足。"
)
RAG_TOOL_HINT = " 你可以调用 mcp_github_* 工具查询仓库、issue、PR 等信息。"


class RagAgent(BaseAgent):
    name = "rag"

    def __init__(self, llm=None) -> None:
        self.store = get_chroma_store()
        self._llm = llm  # 依赖可注入(便于单元测试)

    def _get_llm(self):
        return self._llm or get_llm_by_intent("rag")

    async def run(self, state: AgentState) -> dict:
        question = ""
        if state.get("messages"):
            c = state["messages"][-1].content
            question = c if isinstance(c, str) else str(c)

        # 检索(无文档时优雅降级为通用问答)
        docs = self.store.query(question)
        context = "\n\n".join(docs) if docs else "(暂无相关文档, 基于通用知识回答)"

        tools = get_github_mcp_tools()
        system = RAG_SYSTEM + RAG_TOOL_HINT if tools else RAG_SYSTEM
        prompt = [
            SystemMessage(content=system),
            HumanMessage(content=f"上下文:\n{context}\n\n问题:\n{question}"),
        ]
        text = await self.run_react_loop(self._get_llm(), prompt, tools)

        return {
            "messages": [AIMessage(content=text)],
            "final_answer": text,
            "next_agent": "finish",
        }
