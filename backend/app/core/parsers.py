"""文档文本抽取 — PDF / DOCX / TXT。

所属层级: Core / 基础设施
"""
from io import BytesIO


def extract_text(filename: str, data: bytes) -> str:
    """按扩展名抽取文本内容。"""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext == "pdf":
        return _extract_pdf(data)
    if ext == "docx":
        return _extract_docx(data)
    if ext == "txt":
        return data.decode("utf-8", errors="replace")
    raise ValueError(f"不支持的文件类型: {ext or '未知'}")


def _extract_pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _extract_docx(data: bytes) -> str:
    from docx import Document as DocxDocument

    doc = DocxDocument(BytesIO(data))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
