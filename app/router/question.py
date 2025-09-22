from typing import Annotated, AsyncGenerator, Any, Optional
from uuid import UUID
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from app.db.session import async_session
from app.db.db import Question, User
from app.router.user import get_current_active_user


router = APIRouter(prefix="/question", tags=["question"])


class QuestionCreate(BaseModel):
	content: str
	type: int = Field(1, ge=1, le=3, description="1-单选，2-多选，3-判断")
	options: Any  # 建议传入 {"A":"...","B":"..."} 或 ["..."]
	answer: Any   # 单选传单值或单元素列表；多选传列表；判断传 true/false
	score: float = 1
	analysis: Optional[str] = ""
	level: int = Field(1, ge=1, le=3, description="1-简单，2-中等，3-困难")


class QuestionOut(BaseModel):
	id: UUID
	content: str
	type: int
	options: Any
	answer: Any
	score: float
	analysis: str
	level: int
	creator: UUID
	create_time: datetime
	update_time: datetime
	status: int

	class Config:
		from_attributes = True

async def get_db() -> AsyncGenerator[AsyncSession, None]:
	async with async_session() as session:  # type: ignore[func-returns-value]
		yield session


@router.delete("/{question_id}", description="删除题目（会连带移除与试卷的关联）")
async def delete_question(
	question_id: UUID,
	db: Annotated[AsyncSession, Depends(get_db)],
	current_user: Annotated[User, Depends(get_current_active_user)],
):
	# 仅管理员/教师可以创建题目
	if int(current_user.role) not in (0, 1):
		raise HTTPException(status_code=403, detail="Only teacher/admin can create questions")

	stmt = select(Question).where(Question.id == question_id)
	result = await db.execute(stmt)
	q = result.scalar_one_or_none()
	if not q:
		raise HTTPException(status_code=404, detail="Question not found")
	try:
		await db.delete(q)
		await db.commit()
	except Exception:
		await db.rollback()
		raise
	return {"ok": True}

@router.post("", description="创建题目", response_model=QuestionOut)
async def create_question(
	payload: QuestionCreate,
	db: Annotated[AsyncSession, Depends(get_db)],
	current_user: Annotated[User, Depends(get_current_active_user)],
):
	# 仅管理员/教师可以创建题目
	if int(current_user.role) not in (0, 1):
		raise HTTPException(status_code=403, detail="Only teacher/admin can create questions")

	data = payload.model_dump()

	new_question = Question(**data, creator=current_user.id)
	db.add(new_question)
	await db.commit()
	await db.refresh(new_question)
	return new_question
