"""数据库声明式基类。

所属层级: DB / 基础设施
"""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """所有 ORM 模型的声明式基类。"""
