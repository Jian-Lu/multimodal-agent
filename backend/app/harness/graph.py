"""Harness 层 — StateGraph 编译 + 检查点。

所属层级: Harness

图结构:
    START -> supervisor
    supervisor -(conditional)-> vision | rag | coder | writer | finish(END)
    vision / rag / writer -> END
    coder -> sandbox -> END
"""
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph

from app.agents.coder import CoderAgent
from app.agents.rag import RagAgent
from app.agents.vision import VisionAgent
from app.agents.web_search_agent import WebSearchAgent
from app.agents.writer import WriterAgent
from app.harness.hooks import get_hook_manager
from app.harness.hooks import builtin  # noqa: F401  # 导入即注册内置 hook
from app.harness.state import AgentState
from app.harness.supervisor import supervisor_node
from app.tools.sandbox import SandboxRunner


def build_graph(saver: AsyncSqliteSaver):
    """构建并编译多智能体状态图(注入检查点存储)。"""
    rag = RagAgent()
    vision = VisionAgent()
    coder = CoderAgent()
    writer = WriterAgent()
    web_search = WebSearchAgent()
    sandbox = SandboxRunner()

    hooks = get_hook_manager()

    g = StateGraph(AgentState)
    g.add_node("supervisor", hooks.wrap(supervisor_node, "supervisor"))
    g.add_node("rag", hooks.wrap(rag.run, "rag"))
    g.add_node("vision", hooks.wrap(vision.run, "vision"))
    g.add_node("coder", hooks.wrap(coder.run, "coder"))
    g.add_node("writer", hooks.wrap(writer.run, "writer"))
    g.add_node("web_search", hooks.wrap(web_search.run, "web_search"))
    g.add_node("sandbox", hooks.wrap(sandbox.run, "sandbox"))

    g.add_edge(START, "supervisor")
    g.add_conditional_edges(
        "supervisor",
        lambda s: s.get("next_agent", "finish"),
        {
            "rag": "rag",
            "vision": "vision",
            "coder": "coder",
            "writer": "writer",
            "web_search": "web_search",
            "finish": END,
        },
    )
    g.add_edge("rag", END)
    g.add_edge("vision", END)
    g.add_edge("writer", END)
    g.add_conditional_edges(
        "web_search",
        lambda s: s.get("next_agent", "finish"),
        {"writer": "writer", "finish": END},
    )
    g.add_edge("coder", "sandbox")
    g.add_edge("sandbox", END)

    return g.compile(checkpointer=saver)


# 进程内单例(懒加载)
_graph = None


async def get_graph():
    """获取编译后的图单例(首次调用时创建检查点并编译)。"""
    global _graph
    if _graph is None:
        from app.memory.saver import create_saver

        _graph = build_graph(await create_saver())
    return _graph
