"""Memory 层 — ChromaDB 向量存储与检索。

所属层级: Memory

Phase 2 仅提供检索接口(query), 文档灌入(add)在 Phase 3 完成。
空集合时 query 优雅返回空列表(避免触发 embedding 模型下载)。
"""
import uuid
from pathlib import Path

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.config import BASE_DIR, settings


def _resolve_dir(path: str) -> str:
    """相对路径解析为基于 backend/ 的绝对路径。"""
    if not Path(path).is_absolute():
        return str((BASE_DIR / path).resolve())
    return path


class ChromaStore:
    """ChromaDB 持久化封装。"""

    def __init__(self) -> None:
        self._client = chromadb.PersistentClient(
            path=_resolve_dir(settings.CHROMA_DIR),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self.collection = self._client.get_or_create_collection("documents")

    def add(
        self,
        documents: list[str],
        metadatas: list[dict] | None = None,
        ids: list[str] | None = None,
    ) -> None:
        """写入文档块 (Phase 3 使用)。"""
        ids = ids or [str(uuid.uuid4()) for _ in documents]
        self.collection.add(documents=documents, metadatas=metadatas, ids=ids)

    def query(self, text: str, k: int | None = None) -> list[str]:
        """检索最相关的 k 个文档块, 返回文本列表。空集合返回空列表。"""
        k = k or settings.RAG_TOP_K
        if self.collection.count() == 0:
            return []
        n = min(k, self.collection.count())
        res = self.collection.query(query_texts=[text], n_results=n)
        docs = res.get("documents", [[]])
        return docs[0] if docs and docs[0] else []

    def delete(self, document_id: str) -> None:
        """删除某文档的全部向量块(按 document_id 过滤)。"""
        self.collection.delete(where={"document_id": document_id})


# 全局懒加载单例
_store: ChromaStore | None = None


def get_chroma_store() -> ChromaStore:
    """获取全局 ChromaStore 单例。"""
    global _store
    if _store is None:
        _store = ChromaStore()
    return _store
