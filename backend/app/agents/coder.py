"""Agent 层 — Coder 专家 (代码生成)。

所属层级: Agent
"""
import re

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.agents.base import BaseAgent
from app.harness.state import AgentState
from app.llm.factory import get_llm_by_intent

CODER_SYSTEM = (
    "你是一个资深程序员。根据用户需求生成完整可运行的代码。"
    "只输出代码, 并用 markdown 代码块包裹, 标注语言(如 ```python)。"
)


def extract_code(text: str) -> str:
    """从 markdown 代码块中提取纯代码。"""
    m = re.search(r"```(?:\w+)?\s*\n(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return text.strip()


class CoderAgent(BaseAgent):
    name = "coder"

    async def run(self, state: AgentState) -> dict:
        requirement = ""
        if state.get("messages"):
            c = state["messages"][-1].content
            requirement = c if isinstance(c, str) else str(c)

        prompt = [SystemMessage(content=CODER_SYSTEM), HumanMessage(content=requirement)]
        text = await self.astream_text(get_llm_by_intent("code"), prompt)
        code = extract_code(text)

        return {
            "messages": [AIMessage(content=text)],
            "final_answer": text,
            "code": code,
            "next_agent": "sandbox",
        }
