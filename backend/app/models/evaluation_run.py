"""EvaluationRun 模型 — 评估运行记录 (每次评估结果持久化)。

所属层级: DB / 数据模型

供报告生成与历史查询 (Phase 21) 消费。指标 JSON 用 Text 存 (SQLite 无迁移负担)。
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    layer: Mapped[str] = mapped_column(String(32), nullable=False, index=True)  # routing/quality/e2e
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="live")  # live|dry
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="success")
    summary_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    failures_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
