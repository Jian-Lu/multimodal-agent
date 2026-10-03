"""技能管理端点 — Skill CRUD + 启用/禁用。

所属层级: API / v1
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.response import ok
from app.models import SkillRecord, User
from app.skills import get_skill_registry
from app.skills.schema import Skill

router = APIRouter(prefix="/skills", tags=["skills"])


def _skill_out(skill: Skill) -> dict:
    return skill.model_dump()


@router.get("")
async def list_skills(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """列出所有技能(内置 + 自定义)。"""
    return ok([_skill_out(s) for s in get_skill_registry().list()])


@router.post("")
async def create_skill(
    payload: Skill,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建自定义技能。"""
    registry = get_skill_registry()
    existing = registry.get(payload.name)
    if existing is not None and existing.builtin:
        raise HTTPException(status_code=409, detail="与内置技能同名")

    record = SkillRecord(
        name=payload.name,
        description=payload.description,
        triggers=payload.triggers,
        tools=payload.tools,
        system_prompt_template=payload.system_prompt_template,
        config_schema=payload.config_schema,
        target_agent=payload.target_agent,
        enabled=payload.enabled,
    )
    db.add(record)
    await db.commit()

    payload.builtin = False
    registry.register(payload)
    return ok(_skill_out(payload), message="创建成功")


@router.put("/{name}")
async def update_skill(
    name: str,
    payload: Skill,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """更新/启用禁用技能。内置技能仅允许启用/禁用。"""
    registry = get_skill_registry()
    existing = registry.get(name)
    if existing is None:
        raise HTTPException(status_code=404, detail="技能不存在")

    if existing.builtin:
        existing.enabled = payload.enabled
        return ok(_skill_out(existing), message="更新成功")

    record = await db.get(SkillRecord, name)
    if record is None:
        raise HTTPException(status_code=404, detail="技能不存在")

    record.description = payload.description
    record.triggers = payload.triggers
    record.tools = payload.tools
    record.system_prompt_template = payload.system_prompt_template
    record.config_schema = payload.config_schema
    record.target_agent = payload.target_agent
    record.enabled = payload.enabled
    await db.commit()

    payload.builtin = False
    registry.register(payload)
    return ok(_skill_out(payload), message="更新成功")


@router.delete("/{name}")
async def delete_skill(
    name: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """删除自定义技能(内置禁删)。"""
    registry = get_skill_registry()
    skill = registry.get(name)
    if skill is None:
        raise HTTPException(status_code=404, detail="技能不存在")
    if skill.builtin:
        raise HTTPException(status_code=400, detail="内置技能不可删除")

    record = await db.get(SkillRecord, name)
    if record is not None:
        await db.delete(record)
        await db.commit()

    registry.unregister(name)
    return ok(None, message="删除成功")
