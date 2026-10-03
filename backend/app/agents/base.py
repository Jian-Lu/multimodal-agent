"""Agent 层 — 专家基类。

所属层级: Agent
"""
from abc import ABC, abstractmethod
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage

from app.harness.state import AgentState


class BaseAgent(ABC):
    """所有专家 Agent 的基类。

    子类在 run() 内惰性获取 LLM(get_chat_model/get_vision_model),
    这样即使未配置 API key, 状态图也能正常构建, 错误只在真正调用时暴露。
    """

    name: str = "base"

    @abstractmethod
    async def run(self, state: AgentState) -> dict:
        """执行专家逻辑, 返回状态更新(需含 messages / final_answer)。"""
        raise NotImplementedError

    async def astream_text(self, llm: Any, messages: list[Any]) -> str:
        """流式调用 LLM 并累积为完整文本。

        使用 llm.astream() 以触发 on_chat_model_stream 事件,
        使 graph.astream_events 能捕获到 token 级输出。
        """
        parts: list[str] = []
        async for chunk in llm.astream(messages):
            content = getattr(chunk, "content", "")
            if isinstance(content, str):
                parts.append(content)
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        parts.append(item.get("text", ""))
                    elif isinstance(item, str):
                        parts.append(item)
        return "".join(parts)

    async def run_react_loop(
        self, llm: Any, messages: list[Any], tools: list[Any], max_depth: int = 5
    ) -> str:
        """工具调用循环: LLM → tool_calls → 执行工具 → ToolMessage → 重复。

        无工具时退化为 astream_text(保持纯问答行为);
        工具不存在/执行失败时把错误写进 ToolMessage, 不中断 Agent。
        """
        if not tools:
            return await self.astream_text(llm, messages)
        bound = llm.bind_tools(tools)
        history: list[Any] = list(messages)
        for _ in range(max_depth):
            resp = await bound.ainvoke(history)
            tool_calls = getattr(resp, "tool_calls", None) or []
            if not tool_calls:
                return str(resp.content)
            for tc in tool_calls:
                name = tc["name"]
                args = tc.get("args") or {}
                tool = next((t for t in tools if t.name == name), None)
                if tool is None:
                    result = f"错误: 未知工具 {name}"
                else:
                    try:
                        result = await tool.ainvoke(args)
                    except Exception as e:  # noqa: BLE001 — 工具失败不中断 Agent
                        result = f"工具调用失败: {e}"
                history.append(AIMessage(content="", tool_calls=[tc]))
                history.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))
        return "已达工具调用次数上限, 请基于已有信息作答。"
