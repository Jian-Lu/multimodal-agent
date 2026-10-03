"""统一响应封装 — 所有 API 返回 {code, message, data}。

所属层级: Core / 基础设施

约定: code == 0 表示成功, 非 0 表示业务/系统错误。
"""
from typing import Any


def ok(data: Any = None, message: str = "ok") -> dict[str, Any]:
    """成功响应。"""
    return {"code": 0, "message": message, "data": data}


def fail(code: int = 1, message: str = "error", data: Any = None) -> dict[str, Any]:
    """失败响应。code 通常复用 HTTP 状态码。"""
    return {"code": code, "message": message, "data": data}
