import os
from setuptools import setup, find_packages

# 读取 scripts/requirements.txt 作为依赖
def parse_requirements():
    req_file = os.path.join(os.path.dirname(__file__), "scripts", "requirements.txt")
    if not os.path.exists(req_file):
        return []
    with open(req_file, encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip() and not line.startswith("#")]

setup(
    name="multimodal-agent",
    version="0.1.0",
    description="Multimodal Agent with FastAPI",
    author="Your Name",
    # 关键：将 backend 作为包的根目录
    packages=find_packages(where="backend"),
    package_dir={"": "backend"},
    install_requires=parse_requirements(),
    python_requires=">=3.8",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
    ],
)