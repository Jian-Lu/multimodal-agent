"""文档相关 Pydantic 模型。

所属层级: API / Schema
"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    file_type: str
    chunk_count: int
    created_at: datetime
