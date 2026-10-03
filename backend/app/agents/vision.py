"""Agent 层 — Vision 专家 (多模态图片分析)。

所属层级: Agent
"""
from langchain_core.messages import AIMessage, HumanMessage

from app.agents.base import BaseAgent
from app.harness.state import AgentState
from app.llm.factory import get_llm_by_intent


class VisionAgent(BaseAgent):
    name = "vision"

    async def run(self, state: AgentState) -> dict:
        question = "请描述这张图片"
        if state.get("messages"):
            c = state["messages"][-1].content
            question = c if isinstance(c, str) else str(c)

        images = state.get("images", [])
        content: list = []
        for img in images:
            content.append({"type": "image_url", "image_url": {"url": img}})
        content.append({"type": "text", "text": question})

        text = await self.astream_text(
            get_llm_by_intent("vision", modality="image"), [HumanMessage(content=content)]
        )

        return {
            "messages": [AIMessage(content=text)],
            "final_answer": text,
            "next_agent": "finish",
        }
