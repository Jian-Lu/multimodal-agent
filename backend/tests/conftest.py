"""测试配置 — 使 pytest 从任意目录运行时能 import app 包。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
