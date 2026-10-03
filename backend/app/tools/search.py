"""Tool 层 — Web 搜索提供者 (DuckDuckGo 默认 / Tavily 可选)。

所属层级: Tool

统一异步接口; 同步网络搜索用 asyncio.to_thread 包裹, 避免阻塞事件循环。
"""
import asyncio
from typing import Protocol

from app.config import settings


class SearchProvider(Protocol):
    """搜索提供者接口。"""

    async def search(self, query: str, max_results: int = 5) -> list[dict]:
        """返回 [{title, url, snippet}, ...]。"""
        ...


class DuckDuckGoProvider:
    """DuckDuckGo 搜索(免 key)。"""

    async def search(self, query: str, max_results: int = 5) -> list[dict]:
        return await asyncio.to_thread(self._sync_search, query, max_results)

    def _sync_search(self, query: str, max_results: int) -> list[dict]:
        # 兼容新旧包名: ddgs(新) / duckduckgo_search(旧)
        try:
            from ddgs import DDGS
        except ImportError:  # pragma: no cover
            from duckduckgo_search import DDGS

        with DDGS() as ddgs:
            raw = ddgs.text(query, max_results=max_results)
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("href", ""),
                "snippet": r.get("body", ""),
            }
            for r in raw
        ]


class TavilyProvider:
    """Tavily 搜索(需 TAVILY_API_KEY)。"""

    async def search(self, query: str, max_results: int = 5) -> list[dict]:
        return await asyncio.to_thread(self._sync_search, query, max_results)

    def _sync_search(self, query: str, max_results: int) -> list[dict]:
        from tavily import TavilyClient

        client = TavilyClient(api_key=settings.TAVILY_API_KEY)
        resp = client.search(query, max_results=max_results)
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("content", ""),
            }
            for r in resp.get("results", [])
        ]


def get_search_provider() -> SearchProvider:
    """按 SEARCH_PROVIDER 返回搜索提供者。"""
    if settings.SEARCH_PROVIDER == "tavily":
        return TavilyProvider()
    return DuckDuckGoProvider()
