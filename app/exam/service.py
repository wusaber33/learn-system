from __future__ import annotations
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import and_, or_, select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.cmn.db import ExaminationInfo, PaperQuestion, Question,Examinee, User


class ExamService:
    @staticmethod
    async def create_exam(
        db: AsyncSession,
        name: str,
        type: int,
        difficulty_level: int,
        grade_level: int,
        total_score: float,
        pass_score: float,
        duration: int,
        creator: UUID,
        start_time: datetime,
        end_time: datetime,
    ) -> ExaminationInfo:
        exam = ExaminationInfo(
            name=name,
            type=type,
            difficulty_level=difficulty_level,
            grade_level=grade_level,
            total_score=total_score,
            pass_score=pass_score,
            duration=duration,
            creator=creator,
            start_time=start_time,
            end_time=end_time,
            status=1,
        )
        db.add(exam)
        await db.flush()
        return exam


    @staticmethod
    async def update_exam(
        db: AsyncSession,
        *,
        exam: ExaminationInfo,
        changes: dict,
    ) -> ExaminationInfo:
        # 过滤掉 None 值，避免违反数据库 NOT NULL 约束
        for k, v in changes.items():
            if v is not None:
                setattr(exam, k, v)
        await db.flush()
        return exam


    @staticmethod
    async def select_exam(
        db: AsyncSession,
        *,
        exam_id: UUID,
    ) -> Optional[ExaminationInfo]:
        stmt = (
            select(ExaminationInfo)
            .where(ExaminationInfo.id == exam_id)
            .limit(1)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()
    @staticmethod
    async def add_questions_to_exam(
        db: AsyncSession,
        *,
        exam: ExaminationInfo,
        question_ids: List[UUID],
    ) -> List[UUID]:
        # 去重
        unique_ids = list(dict.fromkeys(question_ids))
        if not unique_ids:
            return []

        # 校验题目存在
        q_stmt = select(Question.id).where(Question.id.in_(unique_ids))
        existing = {row[0] for row in (await db.execute(q_stmt)).all()}
        missing = [qid for qid in unique_ids if qid not in existing]
        if missing:
            raise HTTPException(status_code=400, detail={
                "msg": "Some questions not found",
                "missing_ids": [str(x) for x in missing],
            })

        # 过滤已存在关联
        exist_stmt = (
            select(PaperQuestion.question_id)
            .where(PaperQuestion.examination_info_id == exam.id)
            .where(PaperQuestion.question_id.in_(unique_ids))
        )
        existed = {row[0] for row in (await db.execute(exist_stmt)).all()}
        to_insert = [qid for qid in unique_ids if qid not in existed]

        if not to_insert:
            return []

        new_relations = [
            PaperQuestion(examination_info_id=exam.id, question_id=qid)
            for qid in to_insert
        ]
        db.add_all(new_relations)
        await db.flush()
        return [pq.id for pq in new_relations]


    @staticmethod
    async def get_exam_with_questions(
        db: AsyncSession,
        *,
        exam_id: UUID,
    ) -> Optional[ExaminationInfo]:
        stmt = (
            select(ExaminationInfo)
            .where(ExaminationInfo.id == exam_id)
            .options(selectinload(ExaminationInfo.paper_questions).selectinload(PaperQuestion.question))
            .limit(1)
        )
        return (await db.execute(stmt)).scalar_one_or_none()


    @staticmethod
    async def list_exams_by_creator(
        db: AsyncSession,
        *,
        creator: UUID,
        limit: int,
        offset: int,
        sort_by: str = "create_time",
        sort_order: str = "desc",
    ):
        # 统计
        total = (await db.execute(select(func.count()).where(ExaminationInfo.creator == creator))).scalar_one()
        # 列表
        if sort_by == "difficulty":
            sort_col = ExaminationInfo.difficulty_level
        else:
            sort_col = ExaminationInfo.create_time
        order = [sort_col.asc(), ExaminationInfo.id.asc()] if sort_order == "asc" else [sort_col.desc(), ExaminationInfo.id.desc()]
        stmt = (
            select(ExaminationInfo)
            .where(ExaminationInfo.creator == creator)
            .order_by(*order)
            .limit(limit)
            .offset(offset)
        )
        rows = (await db.execute(stmt)).scalars().all()
        return total, rows


    @staticmethod
    async def list_exams_cursor(
        db: AsyncSession,
        *,
        creator: UUID,
        limit: int,
        last_time: Optional[datetime] = None,
        last_id: Optional[UUID] = None,
    ) -> list[ExaminationInfo]:
        cond = [ExaminationInfo.creator == creator]
        if last_time and last_id:
            cond.append(or_(
                ExaminationInfo.start_time < last_time,
                and_(ExaminationInfo.start_time == last_time, ExaminationInfo.id < last_id)
            ))
        stmt = (
            select(ExaminationInfo)
            .where(and_(*cond))
            .order_by(ExaminationInfo.start_time.desc(), ExaminationInfo.id.desc())
            .limit(limit + 1)
        )
        rows = (await db.execute(stmt)).scalars().all()
        return rows

    @staticmethod
    async def get_exam_detail_by_time(
        db: AsyncSession,
        *,
        start_time: datetime,
        end_time: datetime,
    ) -> list[ExaminationInfo]:
        stmt = (
            select(ExaminationInfo)
            .options(selectinload(ExaminationInfo.examinees).selectinload(Examinee.student).selectinload(User.profile))
            .where(ExaminationInfo.start_time >= start_time)
            .where(ExaminationInfo.end_time <= end_time)
        )
        result = await db.execute(stmt)

        exams = result.scalars().all()
        return exams

    @staticmethod
    async def insert_examinees(
        db: AsyncSession,
        exam_id: UUID,
        body: List[UUID]
    ) -> list[Examinee]:
        examinee_objects = [
            Examinee(
                exam_id=exam_id,
                student_id=student_id,
                status=0,
                submit_time=None
            )
            for student_id in body
        ]
        db.add_all(examinee_objects)
        await db.flush()
        return examinee_objects

    @staticmethod
    async def count_user_papers(db: AsyncSession, user_id: UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(ExaminationInfo)
            .where(ExaminationInfo.creator == user_id)
        )
        result = await db.execute(stmt)
        return result.scalar() or 0