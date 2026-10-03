"""全局配置模块 — 从 .env 加载环境变量(全应用统一配置入口)。

所属层级: Core / 基础设施

所有密钥与地址统一从环境变量读取, 代码中不硬编码。
若项目根目录不存在 .env, 则使用下方默认值(开发可用)。
"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ 目录 (backend/app/config.py -> 上两级)
BASE_DIR = Path(__file__).resolve().parent.parent
# 项目根目录下的 .env
ENV_FILE = BASE_DIR.parent / ".env"


class Settings(BaseSettings):
    """应用配置。

    env_file 指向项目根目录 .env; 找不到时回退到类内默认值。
    """

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---------- 应用 ----------
    APP_NAME: str = "Agent-Harness"
    DEBUG: bool = True
    API_PREFIX: str = "/api/v1"

    # ---------- 安全 ----------
    SECRET_KEY: str = "dev-secret-key-change-me"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    # ---------- 数据库 ----------
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/app.db"
    CHROMA_DIR: str = "./data/chroma"
    CHECKPOINT_DB_PATH: str = "./data/checkpoints.db"

    # ---------- RAG / 检索 ----------
    RAG_TOP_K: int = 4
    CHUNK_SIZE: int = 1000
    CHUNK_OVERLAP: int = 200

    # ---------- Hook System ----------
    HOOK_TOKEN_BUDGET: int = 4000

    # ---------- Evaluation (Layer 1 性能基准) ----------
    EVAL_METRICS_RING: int = 2000       # 每条 (kind, tags) 序列的环形容量
    EVAL_METRICS_WINDOW_S: int = 3600   # /api/v1/eval/metrics 默认统计窗口(秒)

    # ---------- Evaluation (Layer 3 输出质量) ----------
    EVAL_JUDGE_TIMEOUT_S: int = 30      # LLM Judge 单次打分超时(秒)
    EVAL_QUALITY_MIN_SCORE: float = 3.0 # 低于此分计入 failures (各维度 1-5, overall 为均值)

    # ---------- LLM Router ----------
    ROUTE_CHAT_MODEL: str = "qwen2.5-omni-7b"
    ROUTE_VISION_MODEL: str = "qwen2.5-omni-7b"
    ROUTE_CODE_MODEL: str = "qwen2.5-omni-7b"
    ROUTE_DOCUMENT_MODEL: str = "qwen2.5-omni-7b"
    ROUTE_SEARCH_MODEL: str = "qwen2.5-omni-7b"
    ROUTE_RAG_MODEL: str = "qwen2.5-omni-7b"
    ROUTE_ROUTING_MODEL: str = "qwen2.5-omni-7b"
    ROUTE_JUDGE_MODEL: str = "qwen2.5-omni-7b"  # LLM Judge 强模型, 可指向更强 OpenAI 兼容模型
    ROUTE_FALLBACK_MODEL: str = "qwen2.5-omni-7b"

    # ---------- Web Search ----------
    SEARCH_PROVIDER: str = "duckduckgo"  # duckduckgo | tavily
    TAVILY_API_KEY: str = ""
    SEARCH_MAX_RESULTS: int = 5
    SEARCH_CACHE_TTL: int = 300  # 5 分钟

    # ---------- 模型层: 云端(OpenAI 兼容) + 本地(Ollama) ----------
    LLM_PROVIDER: str = "cloud"  # "cloud" | "ollama"

    OPENAI_API_KEY: str = "your-openai-api-key"
    # OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    OPENAI_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    OPENAI_MODEL: str = "qwen2.5-omni-7b"


    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3.1"

    # ---------- 沙箱 (E2B 主 + Docker 备选) ----------
    SANDBOX_BACKEND: str = "e2b"  # "e2b" | "docker"
    E2B_API_KEY: str = ""
    SANDBOX_TIMEOUT: int = 30

    # ---------- 多模态 ----------
    MAX_IMAGE_BYTES: int = 3 * 1024 * 1024  # 3MB

    # ---------- 文档上传 ----------
    UPLOAD_DIR: str = "./data/uploads"
    MAX_UPLOAD_BYTES: int = 20 * 1024 * 1024  # 20MB

    # ---------- CORS ----------
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def cors_origins_list(self) -> list[str]:
        """逗号分隔的 CORS 白名单转 list。"""
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """返回缓存的配置单例。"""
    return Settings()


settings = get_settings()
