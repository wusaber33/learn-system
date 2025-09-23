from datetime import datetime
from typing import Annotated, Optional, AsyncGenerator, List, Literal
from uuid import UUID
import json
from base64 import urlsafe_b64decode, urlsafe_b64encode

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.db import ExaminationInfo, User, PaperQuestion,Question,Examinee,UserInfo
from app.router.user import get_current_active_user
from app.router.question import QuestionOut


router = APIRouter(prefix="/exam", tags=["exam"])

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

class ExamPaper(ExamOut):
    question_ids: List[QuestionOut] = Field(default_factory=list)

class StudentInfo(BaseModel):   
    id: UUID
    name: str
    email: str
    phone: str
    status: Optional[int] = None
    submit_time: Optional[datetime] = None


class ExamDetail(ExamOut):
    examinees: List[StudentInfo] = Field(default_factory=list)


class CursorPage(BaseModel):
    items: List[ExamOut]
    next_cursor: Optional[str] = None
    total: int


class PageOut(BaseModel):
    items: List[ExamOut]
    total: int
    page: int
    page_size: int
    total_pages: int
    has_next: bool
    has_prev: bool

class ExamQuestionCreate(BaseModel):
    question_ids: List[UUID]

async def get_examinees_by_exam_id(db: AsyncSession, exam_id: UUID) -> List[StudentInfo]:
    stmt = (
        select(User.id, User.name, UserInfo.email, UserInfo.phone, User.status, Examinee.submit_time)
        .join(Examinee, Examinee.student_id == User.id)
        .join(UserInfo, UserInfo.user_id == User.id)
        .where(Examinee.exam_id == exam_id)
    )
    result = await db.execute(stmt)
    rows = result.all()
    examinees = [
        StudentInfo(
            id=row[0],
            name=row[1],
            email=row[2],
            phone=row[3],
            status=row[4],
            submit_time=row[5]
        )
        for row in rows
    ]
    return examinees

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

@router.put("/{exam_id}/add_question", description="为试卷添加题目", response_model=list[UUID])
async def add_question_to_exam(
    exam_id: UUID,
    body: ExamQuestionCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    stmt = select(ExaminationInfo).where(ExaminationInfo.id == exam_id)
    result = await db.execute(stmt)
    exam = result.scalar_one_or_none()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    if exam.creator != current_user.id:
        raise HTTPException(status_code=403, detail="Not allowed")

    # 去重输入
    unique_ids = list(dict.fromkeys(body.question_ids))
    if not unique_ids:
        return []

    # 过滤掉已存在关联，避免触发唯一索引
    existing_stmt = (
        select(PaperQuestion.question_id)
        .where(PaperQuestion.examination_info_id == exam.id)
        .where(PaperQuestion.question_id.in_(unique_ids))
    )
    existing = {row[0] for row in (await db.execute(existing_stmt)).all()}
    to_insert = [qid for qid in unique_ids if qid not in existing]

    if to_insert:
        stmt = (
            pg_insert(PaperQuestion)
            .values(
                [
                    {
                        "examination_info_id": exam.id,
                        "question_id": qid,
                        "creator": current_user.id,
                    }
                    for qid in to_insert
                ]
            )
        )
        await db.execute(stmt)
        await db.commit()
    return to_insert

@router.get("/content/{exam_id}", description="获取试卷详情", response_model=ExamPaper)
async def get_paper_content(
    exam_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    stmt = select(ExaminationInfo).where(ExaminationInfo.id == exam_id)
    result = await db.execute(stmt)
    exam = result.scalar_one_or_none()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    # 一次联表查询题目，按关联表顺序返回
    q_stmt = (
        select(Question)
        .join(PaperQuestion, PaperQuestion.question_id == Question.id)
        .where(PaperQuestion.examination_info_id == exam.id)
        .order_by(PaperQuestion.id.asc())
    )
    q_result = await db.execute(q_stmt)
    questions = q_result.scalars().all()

    exam_data = ExamPaper.model_validate(exam)
    exam_data.question_ids = questions
    return exam_data

@router.get(
    "/list",
    description="查询指定教师的所有试卷（分页），返回总数并处理页码边界",
    response_model=PageOut,
)
async def list_teacher_exams(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    limit: int = Query(10, ge=1, le=100, description="每页数量"),
    page: int = Query(1, description="页码(从1开始，可小于1将被修正为1)"),
    sort_by: Literal["create_time", "difficulty"] = Query("create_time"),
    sort_order: Literal["asc", "desc"] = Query("desc"),
):
    # 总数统计
    count_stmt = select(func.count()).where(ExaminationInfo.creator == current_user.id)
    total = (await db.execute(count_stmt)).scalar_one()

    # 页码边界处理
    if page < 1:
        page = 1
    total_pages = (total + limit - 1) // limit if total > 0 else 0
    if total_pages > 0 and page > total_pages:
        page = total_pages
    # 计算偏移
    offset = (page - 1) * limit if total_pages > 0 else 0
    if offset < 0:
        offset = 0
    # 选择排序字段
    if sort_by == "difficulty":
        sort_col = ExaminationInfo.difficulty_level
    else:
        sort_col = ExaminationInfo.create_time

    # 升降序处理，增加次级排序确保稳定顺序
    if sort_order == "asc":
        order_clause = [sort_col.asc(), ExaminationInfo.id.asc()]
    else:
        order_clause = [sort_col.desc(), ExaminationInfo.id.desc()]

    stmt = (
        select(ExaminationInfo)
        .where(ExaminationInfo.creator == current_user.id)
        .order_by(*order_clause)
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    items = result.scalars().all()
    return PageOut(
        items=items,
        total=total,
        page=page,
        page_size=limit,
        total_pages=total_pages,
        has_next=(page < total_pages),
        has_prev=(page > 1 and total_pages > 0),
    )

def _encode_cursor(dt: datetime, id_: UUID) -> str:
    payload = {"t": dt.isoformat(), "id": str(id_)}
    raw = json.dumps(payload).encode("utf-8")
    return urlsafe_b64encode(raw).decode("utf-8")


def _decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        raw = urlsafe_b64decode(cursor.encode("utf-8"))
        payload = json.loads(raw.decode("utf-8"))
        t = datetime.fromisoformat(payload["t"])  # naive/aware 由客户端传入决定
        return t, UUID(payload["id"])  # type: ignore[arg-type]
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid cursor")


@router.get(
    "/cursor",
    description="查询指定教师的所有试卷（游标），按考试开始时间(start_time)降序分页，返回 next_cursor",
    response_model=CursorPage,
)
async def list_teacher_exams_cursor(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    limit: int = Query(10, ge=1, le=100),
    cursor: Optional[str] = Query(None, description="上一次响应返回的 next_cursor"),
):
    # 统一使用 start_time DESC, id DESC 作为顺序（确定性）
    conditions = [ExaminationInfo.creator == current_user.id]

    if cursor:
        last_time, last_id = _decode_cursor(cursor)
        # 对应 (start_time, id) < (last_time, last_id) 按降序遍历下一页
        cond = or_(
            ExaminationInfo.start_time < last_time,
            and_(
                ExaminationInfo.start_time == last_time,
                ExaminationInfo.id < last_id,
            ),
        )
        conditions.append(cond)

    stmt = (
        select(ExaminationInfo)
        .where(and_(*conditions))
        .order_by(ExaminationInfo.start_time.desc(), ExaminationInfo.id.desc())
        .limit(limit + 1)  # 多取一个判断是否还有下一页
    )

    # 统计总数
    count_stmt = select(func.count()).where(ExaminationInfo.creator == current_user.id)
    total = (await db.execute(count_stmt)).scalar_one()

    result = await db.execute(stmt)
    rows = result.scalars().all()

    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = None
    if has_more:
        last = items[-1]
        next_cursor = _encode_cursor(last.start_time, last.id)
    return CursorPage(items=items, next_cursor=next_cursor, total=total)



@router.get("/detail",description="获取某个时间段考试记录及相关人员信息",response_model=List[ExamDetail])
async def get_exam_details(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    start_time: datetime,
    end_time: datetime,
):
    stmt = (
        select(ExaminationInfo)
        .where(ExaminationInfo.start_time >= start_time)
        .where(ExaminationInfo.end_time <= end_time)
    )
    result = await db.execute(stmt)
    exams = result.scalars().all()

    exam_details = []
    for exam in exams:
        examinees = await get_examinees_by_exam_id(db, exam.id)
        # 使用 Pydantic v2 的模型校验从 ORM 转换
        base = ExamOut.model_validate(exam)
        exam_details.append(ExamDetail(**base.model_dump(), examinees=examinees))

    return exam_details