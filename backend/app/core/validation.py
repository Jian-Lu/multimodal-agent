"""请求校验工具 — 多模态图片大小校验(3MB 上限)。

所属层级: Core / 基础设施
"""
from fastapi import HTTPException

from app.config import settings


def validate_image_base64(images: list[str]) -> None:
    """校验 Base64 图片长度, 超限抛出 413。

    Base64 编码膨胀率约 4/3, 故 3MB 原始字节 ≈ 4MB Base64 字符。
    前端已用 browser-image-compression 压到 ≤3MB, 此处为后端兜底校验。
    """
    limit = settings.MAX_IMAGE_BYTES * 4 // 3
    for img in images:
        if img and len(img) > limit:
            raise HTTPException(
                status_code=413,
                detail="图片大小超过 3MB 限制, 请压缩后重试",
            )
