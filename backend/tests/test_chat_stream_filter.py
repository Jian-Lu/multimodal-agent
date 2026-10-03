"""聊天流过滤 — supervisor 路由 JSON 不泄漏到前端 SSE。

覆盖两点:
1. chat.py 的 _should_skip_stream: 非聊天模型流 / 带 routing tag 的内部流跳过,
   普通叶子 agent 流保留。
2. supervisor 路由调用确实携带 config tags=["routing"], 供上述过滤使用。
"""
import asyncio

from langchain_core.messages import HumanMessage

from app.api.v1.chat import _should_skip_stream
from app.harness.state import RoutingDecision
from app.harness.supervisor import supervisor_node
from app.skills import load_builtin_skills


def run(coro):
    return asyncio.run(coro)


def test_should_skip_routing_stream():
    # 非聊天模型事件 → 跳过
    assert _should_skip_stream({"event": "on_chat_start"}) is True
    # 普通聊天模型流(叶子 agent 的答复) → 不过滤
    assert _should_skip_stream({"event": "on_chat_model_stream", "tags": []}) is False
    assert _should_skip_stream({"event": "on_chat_model_stream"}) is False
    # supervisor 内部路由流(routing tag) → 跳过
    assert (
        _should_skip_stream(
            {"event": "on_chat_model_stream", "tags": ["routing", "some"]}
        )
        is True
    )


class _RecordingLLM:
    """记录 ainvoke config 的假 RoutedLLM, 仅用于路由判定。"""

    def __init__(self):
        self.configs: list = []

    def with_structured_output(self, schema):
        return self

    async def ainvoke(self, messages, **kwargs):
        self.configs.append(kwargs.get("config"))
        return RoutingDecision(next_agent="writer", reasoning="test", confidence=0.9)


def test_supervisor_routing_invokes_with_routing_tag(monkeypatch):
    load_builtin_skills()
    llm = _RecordingLLM()
    monkeypatch.setattr("app.harness.supervisor.get_llm_by_intent", lambda intent: llm)

    result = run(
        supervisor_node(
            {
                "messages": [HumanMessage(content="帮我写出最近一周的新闻热点趋势")],
                "mode": "chat",
            }
        )
    )

    assert result["next_agent"] == "writer"
    assert llm.configs, "应发生一次路由调用"
    assert llm.configs[0] == {"tags": ["routing"]}
