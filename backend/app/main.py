"""FastAPI 应用入口 — CORS、路由注册、统一异常处理、建表。

所属层级: API / 入口
"""
import sys
from pathlib import Path

# 直接运行 `python main.py`(如 PyCharm 右键运行) 时, 把 backend/ 加入 sys.path 以解析 app 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import auth, chat, documents, evaluation, health, sessions, skills
from app.config import settings
from app.core.response import fail, ok
from app.db.session import AsyncSessionLocal, init_db
from app.evaluation import install_metrics_telemetry
from app.mcp_sdk.github_client import init_github_mcp, shutdown_github_mcp
from app.skills import load_builtin_skills, load_custom_skills


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期: 启动时建表 + 装配技能 + 连接 GitHub MCP + 安装评估遥测(一次性)。"""
    await init_db()
    install_metrics_telemetry()  # Layer 1: TimingHook 常驻采集 hook_latency
    load_builtin_skills()
    async with AsyncSessionLocal() as db:
        await load_custom_skills(db)
    await init_github_mcp()
    yield
    await shutdown_github_mcp()


app = FastAPI(title=settings.APP_NAME, lifespan=lifespan, debug=settings.DEBUG)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- 统一异常处理 → {code, message, data} ----------
@app.exception_handler(HTTPException)
async def http_exc_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=fail(exc.status_code, str(exc.detail)))


@app.exception_handler(RequestValidationError)
async def validation_exc_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content=fail(422, "请求参数校验失败"))


@app.exception_handler(Exception)
async def unhandled_exc_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content=fail(500, "服务器内部错误"))


# ---------- 路由注册 ----------
app.include_router(health.router, prefix=settings.API_PREFIX)
app.include_router(auth.router, prefix=settings.API_PREFIX)
app.include_router(chat.router, prefix=settings.API_PREFIX)
app.include_router(documents.router, prefix=settings.API_PREFIX)
app.include_router(skills.router, prefix=settings.API_PREFIX)
app.include_router(sessions.router, prefix=settings.API_PREFIX)
app.include_router(evaluation.router, prefix=settings.API_PREFIX)


@app.get("/")
async def root() -> dict:
    return ok({"service": settings.APP_NAME, "docs": "/docs"})


if __name__ == "__main__":
    import uvicorn
    print("")
    uvicorn.run(app, host="127.0.0.1", port=8010)
