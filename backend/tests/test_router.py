"""Model 层 — LLM Router 单元测试。

所属层级: Model / Gateway
"""
import asyncio

from app.config import settings
from app.llm.factory import (
    INTENT_MODEL_MAP,
    IntentClassifier,
    RoutedLLM,
    resolve_model_name,
)


def run(coro):
    return asyncio.run(coro)


async def collect(agen):
    return [c async for c in agen]


# ---------- 意图分类 ----------
def test_classify_vision():
    assert IntentClassifier.classify("这是什么", images=["data:image/png;base64,x"]) == "vision"


def test_classify_code():
    assert IntentClassifier.classify("帮我写一个 python 函数") == "code"


def test_classify_document():
    assert IntentClassifier.classify("把这份内容写成报告") == "document"


def test_classify_search():
    assert IntentClassifier.classify("搜索一下2024年AI趋势") == "search"


def test_classify_chat():
    assert IntentClassifier.classify("你好呀") == "chat"


def test_classify_document_mode():
    assert IntentClassifier.classify("随便什么", mode="document") == "document"


# ---------- 模型映射 ----------
def test_intent_model_map_resolves():
    assert INTENT_MODEL_MAP["code"] == settings.ROUTE_CODE_MODEL
    assert INTENT_MODEL_MAP["vision"] == settings.ROUTE_VISION_MODEL
    assert resolve_model_name("unknown_intent") == settings.ROUTE_CHAT_MODEL


# ---------- RoutedLLM fallback ----------
class FakeModel:
    def __init__(self, response="ok", fail=False):
        self.response = response
        self.fail = fail

    async def astream(self, messages, **kwargs):
        if self.fail:
            raise RuntimeError("primary down")
        yield type("Chunk", (), {"content": self.response})()

    async def ainvoke(self, messages, **kwargs):
        if self.fail:
            raise RuntimeError("primary down")
        return type("Msg", (), {"content": self.response})()


def test_routed_llm_passes_through():
    r = RoutedLLM(FakeModel("primary"), FakeModel("fallback"), "chat")
    chunks = run(collect(r.astream([])))
    assert [c.content for c in chunks] == ["primary"]


def test_routed_llm_fallback():
    r = RoutedLLM(FakeModel(fail=True), FakeModel("fallback"), "chat")
    chunks = run(collect(r.astream([])))
    assert [c.content for c in chunks] == ["fallback"]


def test_routed_llm_ainvoke_fallback():
    r = RoutedLLM(FakeModel(fail=True), FakeModel("fallback"), "chat")
    msg = run(r.ainvoke([]))
    assert msg.content == "fallback"


def test_routed_llm_reraises_without_fallback():
    r = RoutedLLM(FakeModel(fail=True), None, "chat")
    try:
        run(collect(r.astream([])))
        assert False, "should have raised"
    except RuntimeError:
        pass
