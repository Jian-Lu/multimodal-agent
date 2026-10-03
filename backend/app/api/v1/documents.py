"""文档管理端点 — RAG 文档上传/列表/删除。

所属层级: API / v1
"""
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.config import BASE_DIR, settings
from app.core.parsers import extract_text
from app.core.response import ok
from app.memory.chroma import get_chroma_store
from app.models import Document, User
from app.schemas.document import DocumentOut

router = APIRouter(prefix="/documents", tags=["documents"])

ALLOWED_TYPES = {"pdf", "docx", "txt"}


def _file_type(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def _resolve_upload_dir() -> Path:
    p = Path(settings.UPLOAD_DIR)
    if not p.is_absolute():
        p = BASE_DIR / p
    p.mkdir(parents=True, exist_ok=True)
    return p


def _doc_out(doc: Document) -> dict:
    return DocumentOut.model_validate(doc).model_dump(mode="json")


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """上传文档: 抽取 -> 切块 -> 向量化 -> 落库。"""
    filename = file.filename or "unnamed"
    file_type = _file_type(filename)
    if file_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail="仅支持 PDF/DOCX/TXT 文件")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="文件为空")
    if len(data) > settings.MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="文件大小超过 20MB 限制")

    try:
        text = extract_text(filename, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"解析失败: {e}") from e

    text = text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="文档未提取到文本内容")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.CHUNK_SIZE, chunk_overlap=settings.CHUNK_OVERLAP
    )
    chunks = splitter.split_text(text)

    doc_id = str(uuid.uuid4())
    store = get_chroma_store()
    metadatas = [
        {"document_id": doc_id, "user_id": user.id, "filename": filename} for _ in chunks
    ]
    store.add(chunks, metadatas=metadatas)

    doc = Document(
        id=doc_id,
        user_id=user.id,
        filename=filename,
        file_type=file_type,
        chunk_count=len(chunks),
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    (_resolve_upload_dir() / f"{doc_id}.{file_type}").write_bytes(data)

    return ok(_doc_out(doc), message="上传成功")


@router.get("")
async def list_documents(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """列出当前用户的文档(按创建时间倒序)。"""
    result = await db.scalars(
        select(Document)
        .where(Document.user_id == user.id)
        .order_by(Document.created_at.desc())
    )
    docs = result.all()
    return ok([_doc_out(d) for d in docs])


@router.delete("/{document_id}")
async def delete_document(
    document_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """删除文档: 校验归属 -> 删向量 + 记录 + 原始文件。"""
    doc = await db.scalar(
        select(Document).where(Document.id == document_id, Document.user_id == user.id)
    )
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")

    get_chroma_store().delete(document_id)
    await db.delete(doc)
    await db.commit()

    f = _resolve_upload_dir() / f"{document_id}.{doc.file_type}"
    if f.exists():
        f.unlink()

    return ok(None, message="删除成功")
