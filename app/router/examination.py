from datetime import datetime
from typing import Annotated, Optional, AsyncGenerator, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session
from app.db.db import ExaminationInfo, User
from app.router.user import get_current_active_user


router = APIRouter(prefix="/exam", tags=["exam"])


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:  # type: ignore[func-returns-value]
        yield session


class ExamCreate(BaseModel):
    name: str
    type: int = Field(1, description="1-期中，2-期末，3-模拟，4-竞赛，5-练习")
    difficulty_level: int = Field(1, description="1-简单，2-中等，3-困难")
    grade_level: int = Field(1, description="1-小学，2-初中，3-高中，4-大学")
    total_score: float = 100
    pass_score: float = 60
    duration: int = 90
    start_time: datetime
    end_time: datetime


class ExamUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[int] = None
    difficulty_level: Optional[int] = None
    grade_level: Optional[int] = None
    total_score: Optional[float] = None
    pass_score: Optional[float] = None
    duration: Optional[int] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    status: Optional[int] = None


class ExamOut(BaseModel):
    id: UUID
    name: str
    type: int
    difficulty_level: int
    grade_level: int
    total_score: float
    pass_score: float
    duration: int
    creator: UUID
    start_time: datetime
    end_time: datetime
    status: int

    class Config:
        from_attributes = True


@router.post("", description="创建试卷", response_model=ExamOut)
async def create_exam_info(
    body: ExamCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    exam = ExaminationInfo(
        name=body.name,
        type=body.type,
        difficulty_level=body.difficulty_level,
        grade_level=body.grade_level,
        total_score=body.total_score,
        pass_score=body.pass_score,
        duration=body.duration,
        creator=current_user.id,  # ExaminationInfo.creator 是 UUID
        start_time=body.start_time,
        end_time=body.end_time,
        status=1,
    )
    db.add(exam)
    await db.commit()
    await db.refresh(exam)
    return exam


@router.put("/{exam_id}", description="更新试卷信息", response_model=ExamOut)
async def update_exam_info(
    exam_id: UUID,
    body: ExamUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    stmt = select(ExaminationInfo).where(ExaminationInfo.id == exam_id)
    result = await db.execute(stmt)
    exam = result.scalar_one_or_none()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    # 只允许创建者更新（可选安全约束）
    if exam.creator != current_user.id:
        raise HTTPException(status_code=403, detail="Not allowed")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(exam, field, value)
    await db.commit()
    await db.refresh(exam)
    return exam


@router.get("", description="查询指定教师的所有试卷（分页）", response_model=List[ExamOut])
async def list_teacher_exams(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    stmt = (
        select(ExaminationInfo)
        .where(ExaminationInfo.creator == current_user.id)
        .order_by(ExaminationInfo.create_time.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    exams = result.scalars().all()
    return exams