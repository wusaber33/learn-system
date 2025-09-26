from typing import Annotated, AsyncGenerator, Any, Optional
from uuid import UUID
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from app.cmn.session import get_db
from app.cmn.db import Question, User
from app.user.view import get_current_active_user
from app.question.schema import QuestionCreate, QuestionOut
from app.question.service import QuestionService


router = APIRouter(prefix="/question", tags=["question"])

@router.delete("/{question_id}", description="删除题目（会连带移除与试卷的关联）")
async def delete_question(
	question_id: UUID,
	db: Annotated[AsyncSession, Depends(get_db)],
	current_user: Annotated[User, Depends(get_current_active_user)],
):
	# 仅管理员/教师可以创建题目
	if int(current_user.role) not in (0, 1):
		raise HTTPException(status_code=403, detail="Only teacher/admin can create questions")
	await QuestionService.delete_question(db, question_id=question_id)
	return {"ok": True}

@router.post("", description="创建题目", response_model=list[QuestionOut])
async def create_question(
	payload: list[QuestionCreate],
	db: Annotated[AsyncSession, Depends(get_db)],
	current_user: Annotated[User, Depends(get_current_active_user)],
):
	# 仅管理员/教师可以创建题目
	if int(current_user.role) not in (0, 1):
		raise HTTPException(status_code=403, detail="Only teacher/admin can create questions")

	items = [it.model_dump() for it in payload]
	questions = await QuestionService.create_questions(db, creator=current_user.id, items=items)
	return questions
