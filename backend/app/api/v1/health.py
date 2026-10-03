"""健康检查端点。

所属层级: API / v1
"""
from fastapi import APIRouter

from app.core.response import ok

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    """服务健康检查。"""
    return ok({"status": "healthy", "service": "agent-harness"})
