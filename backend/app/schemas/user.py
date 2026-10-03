"""用户相关 Pydantic 模型。

所属层级: API / Schema
"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    username: str
    created_at: datetime
