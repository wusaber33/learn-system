from __future__ import annotations
from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cmn.db import Question


class QuestionService:
    @staticmethod
    async def create_questions(db: AsyncSession, creator: UUID, items: List[dict]) -> list[Question]:
        try:
            questions = [Question(**data, creator=creator) for data in items]
            db.add_all(questions)
            await db.flush()
            await db.commit()
        except Exception:
            await db.rollback()
            raise
        return questions

    @staticmethod
    async def delete_question(db: AsyncSession, *, question_id: UUID) -> None:
        try:
            q = await QuestionService.select_question(db, question_id=question_id)
            if not q:
                raise HTTPException(status_code=404, detail="Question not found")
            db.delete(q)
            await db.flush()
            await db.commit()
        except Exception:
            await db.rollback()
            raise

    @staticmethod
    async def select_questions(db: AsyncSession, *, question_ids: List[UUID]) -> List[Question]:
        stmt = select(Question).where(Question.id.in_(question_ids))
        result = await db.execute(stmt)
        return result.scalars().all()

    @staticmethod
    async def select_question(db: AsyncSession, *, question_id: UUID) -> Optional[Question]:
        stmt = select(Question).where(Question.id == question_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()