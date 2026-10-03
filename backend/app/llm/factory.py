"""Model 层 — 统一模型工厂 + LLM Router。

所属层级: Model / Gateway

- 通过 LLM_PROVIDER 切换云端(OpenAI 兼容端点)与本地(Ollama)。
- LLM Router 按意图/模态动态选择模型实例, 决策用规则/关键词(不调 LLM),
  主模型运行时失败自动切换备用模型。
"""
import logging
import time
from typing import Any, AsyncIterator, Literal

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

from app.config import settings
from app.evaluation.metrics_collector import get_metrics_collector

logger = logging.getLogger("llm.router")

Intent = Literal["chat", "vision", "code", "document", "search", "rag", "routing", "judge"]


# ---------- 低层模型构建 ----------
def _cloud_model(model_name: str, temperature: float = 0.2) -> ChatOpenAI:
    """OpenAI 兼容端点模型。"""
    return ChatOpenAI(
        model=model_name,
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL,
        temperature=temperature,
    )


def _ollama_model(model_name: str, temperature: float = 0.2) -> ChatOllama:
    """本地 Ollama 模型。"""
    return ChatOllama(
        model=model_name,
        base_url=settings.OLLAMA_BASE_URL,
        temperature=temperature,
    )


def _build(model_name: str, temperature: float = 0.2) -> BaseChatModel:
    """按 LLM_PROVIDER 构建指定名称的模型。"""
    if settings.LLM_PROVIDER == "ollama":
        return _ollama_model(model_name, temperature)
    return _cloud_model(model_name, temperature)


# ---------- 意图分类(规则/关键词, 不调 LLM) ----------
class IntentClassifier:
    """轻量意图分类器。"""

    CODE_KEYWORDS = (
        "写代码", "生成代码", "写个函数", "写个脚本", "实现一个", "函数", "脚本",
        "算法", "bug", "修复", "python", "javascript", "typescript", "java", "golang",
        "rust", "代码", "编程",
    )
    SEARCH_KEYWORDS = (
        "搜索", "查一下", "搜一下", "最新", "趋势", "新闻", "资讯",
        "search", "2024", "2025", "2026",
    )
    DOCUMENT_KEYWORDS = (
        "写报告", "生成文档", "总结成", "写成报告", "报告", "markdown 文档", "文档",
    )

    @classmethod
    def classify(
        cls, text: str, images: list[str] | None = None, mode: str = "chat"
    ) -> Intent:
        """返回意图(优先级: 图片 > document 模式 > code > search > document > chat)。"""
        if images:
            return "vision"
        if mode == "document":
            return "document"
        t = (text or "").lower()
        if any(k in t for k in cls.CODE_KEYWORDS):
            return "code"
        if any(k in t for k in cls.SEARCH_KEYWORDS):
            return "search"
        if any(k in t for k in cls.DOCUMENT_KEYWORDS):
            return "document"
        return "chat"


# ---------- 模型映射(可用 .env 覆盖) ----------
INTENT_MODEL_MAP: dict[str, str] = {
    "chat": settings.ROUTE_CHAT_MODEL,
    "vision": settings.ROUTE_VISION_MODEL,
    "code": settings.ROUTE_CODE_MODEL,
    "document": settings.ROUTE_DOCUMENT_MODEL,
    "search": settings.ROUTE_SEARCH_MODEL,
    "rag": settings.ROUTE_RAG_MODEL,
    "routing": settings.ROUTE_ROUTING_MODEL,
    "judge": settings.ROUTE_JUDGE_MODEL,
}


def resolve_model_name(intent: str) -> str:
    """intent -> 主模型名(未识别则回退 chat 模型)。"""
    return INTENT_MODEL_MAP.get(intent, settings.ROUTE_CHAT_MODEL)


# ---------- RoutedLLM (fallback 包装) ----------
class RoutedLLM:
    """带 fallback 的模型包装: 主模型运行时失败自动切备用。"""

    def __init__(self, primary: Any, fallback: Any | None, intent: str,
                 model_name: str = "") -> None:
        self.primary = primary
        self.fallback = fallback
        self.intent = intent
        self.model_name = model_name
        self.provider = settings.LLM_PROVIDER

    async def astream(self, messages: list[Any], **kwargs) -> AsyncIterator[Any]:
        try:
            async for chunk in self.primary.astream(messages, **kwargs):
                yield chunk
        except Exception as e:  # noqa: BLE001
            logger.warning("Router: intent=%s 主模型失败, 切 fallback: %s", self.intent, e)
            if self.fallback is not None:
                async for chunk in self.fallback.astream(messages, **kwargs):
                    yield chunk
            else:
                raise

    async def ainvoke(self, messages: list[Any], **kwargs) -> Any:
        try:
            result = await self.primary.ainvoke(messages, **kwargs)
        except Exception as e:  # noqa: BLE001
            logger.warning("Router: intent=%s 主模型失败, 切 fallback: %s", self.intent, e)
            if self.fallback is None:
                raise
            result = await self.fallback.ainvoke(messages, **kwargs)
        self._record_usage(result)
        return result

    def _record_usage(self, result: Any) -> None:
        """ainvoke 成功后采集 token 用量 (astream 流式路径暂不采集)。"""
        try:
            um = getattr(result, "usage_metadata", None) or {}
            total = um.get("total_tokens") or um.get("total_token_count") or 0
            if not total:
                return
            get_metrics_collector().record(
                "token_usage", count=int(total),
                intent=self.intent, model=self.model_name or "",
            )
        except Exception as e:  # noqa: BLE001 — 采集异常不影响主流程
            logger.warning("Router: token 用量采集失败: %s", e)

    def bind_tools(self, tools: list[Any]) -> "RoutedLLM":
        """绑定工具(供 MCP Agent 等工具调用场景), 保持 fallback 语义。"""
        primary = self.primary.bind_tools(tools)
        fallback = self.fallback.bind_tools(tools) if self.fallback is not None else None
        return RoutedLLM(primary, fallback, self.intent, self.model_name)

    def with_structured_output(self, schema: Any) -> "RoutedLLM":
        """绑定结构化输出 Schema(供 Supervisor 等路由场景), 保持 fallback 语义。"""
        primary = self.primary.with_structured_output(schema)
        fallback = (
            self.fallback.with_structured_output(schema)
            if self.fallback is not None
            else None
        )
        return RoutedLLM(primary, fallback, self.intent, self.model_name)


# ---------- 统一入口 ----------
def get_chat_model(temperature: float = 0.2) -> BaseChatModel:
    """返回默认文本聊天模型(向后兼容)。"""
    name = settings.OLLAMA_MODEL if settings.LLM_PROVIDER == "ollama" else settings.OPENAI_MODEL
    return _build(name, temperature)


def get_vision_model(temperature: float = 0.2) -> BaseChatModel:
    """返回默认视觉模型(向后兼容)。"""
    name = settings.OLLAMA_MODEL if settings.LLM_PROVIDER == "ollama" else settings.OPENAI_MODEL
    return _build(name, temperature)


def get_llm_by_intent(
    intent: str,
    modality: str | None = None,
    complexity: str | None = None,
    temperature: float = 0.2,
) -> RoutedLLM:
    """按意图返回模型实例(含 fallback)。"""
    t0 = time.perf_counter()
    model_name = resolve_model_name(intent)
    primary = _build(model_name, temperature)
    fallback = (
        _build(settings.ROUTE_FALLBACK_MODEL, temperature)
        if settings.ROUTE_FALLBACK_MODEL
        else None
    )
    decision_ms = (time.perf_counter() - t0) * 1000
    logger.info(
        "Router: intent=%s modality=%s complexity=%s -> model=%s fallback=%s (decision %.2fms)",
        intent,
        modality,
        complexity,
        model_name,
        settings.ROUTE_FALLBACK_MODEL or "-",
        decision_ms,
    )
    try:
        get_metrics_collector().record(
            "router_latency", value=decision_ms,
            intent=intent, model=model_name, provider=settings.LLM_PROVIDER,
        )
    except Exception:  # noqa: BLE001 — 指标采集异常不影响路由
        pass
    return RoutedLLM(primary, fallback, intent, model_name)
