"""MCP 敏感字段加密 — Fernet。

所属层级: MCP Infrastructure

密钥优先级: MCP_ENCRYPTION_KEY 环境变量 > 自动生成的密钥文件(data/.mcp_enc_key)。
加密失败/密钥不匹配时解密返回空值, 保证不抛异常中断流程。
"""
import json
import logging
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from app.config import BASE_DIR
from app.mcp_sdk.config import mcp_settings

logger = logging.getLogger("mcp.crypto")

_KEY_FILE = BASE_DIR / "data" / ".mcp_enc_key"


def _load_or_create_key() -> bytes:
    """读取或生成 Fernet 密钥(环境变量优先, 其次密钥文件)。"""
    env_key = (mcp_settings.ENCRYPTION_KEY or "").strip()
    if env_key:
        return env_key.encode("utf-8")
    if _KEY_FILE.exists():
        return _KEY_FILE.read_bytes()
    key = Fernet.generate_key()
    _KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    _KEY_FILE.write_bytes(key)
    logger.warning("[MCP] 未配置 MCP_ENCRYPTION_KEY, 已自动生成密钥文件 %s", _KEY_FILE)
    return key


_fernet = Fernet(_load_or_create_key())


def encrypt_text(plain: str) -> str:
    """加密字符串, 空值原样返回。"""
    if not plain:
        return ""
    return _fernet.encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt_text(token: str) -> str:
    """解密字符串, 失败返回空串(不抛异常)。"""
    if not token:
        return ""
    try:
        return _fernet.decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeDecodeError):  # noqa: BLE001 — 密钥不匹配/数据损坏
        logger.warning("[MCP] 解密失败(密钥不匹配或数据损坏), 返回空值")
        return ""


def encrypt_dict(data: dict | None) -> str:
    """dict -> 加密后的 JSON 字符串(env/headers 存储)。"""
    return encrypt_text(json.dumps(data or {}, ensure_ascii=False))


def decrypt_dict(token: str) -> dict:
    """解密 JSON 字符串 -> dict, 失败返回空 dict。"""
    text = decrypt_text(token)
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}
