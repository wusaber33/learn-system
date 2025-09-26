from datetime import datetime
from typing import Annotated, Optional, List, Literal
from uuid import UUID
import json
from base64 import urlsafe_b64decode, urlsafe_b64encode
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.cmn.session import get_db
from app.cmn.db import ExaminationInfo, User
from app.user.view import get_current_active_user
from app.exam.service import (
    ExamService
)
import app.exam.schema as exam_schema

router = APIRouter(prefix="/exam", tags=["exam"])



@router.post("", description="创建试卷", response_model=exam_schema.ExamOut)
async def create_exam_info(
    body: exam_schema.ExamCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    exam = await ExamService.create_exam(
        db,
        name=body.name,
        type=body.type,
        difficulty_level=body.difficulty_level,
        grade_level=body.grade_level,
        total_score=body.total_score,
        pass_score=body.pass_score,
        duration=body.duration,
        creator=current_user.id,
        start_time=body.start_time,
        end_time=body.end_time,
    )
    response = exam_schema.ExamOut.model_validate(exam)  # 确保能正确序列化
    await db.commit()
    return response


@router.put("/{exam_id}", description="更新试卷信息", response_model=exam_schema.ExamOut)
async def update_exam_info(
    exam_id: UUID,
    body: exam_schema.ExamUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    exam = await ExamService.select_exam(db, exam_id=exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    # 只允许创建者更新（可选安全约束）
    if exam.creator != current_user.id:
        raise HTTPException(status_code=403, detail="Not allowed")
    exam = await ExamService.update_exam(db, exam=exam, changes=body.model_dump(exclude_unset=True))
    await db.commit()
    response = exam_schema.ExamOut.model_validate(exam)  # 确保能正确序列化
    return response

@router.put("/{exam_id}/add_question", description="为试卷添加题目", response_model=list[UUID])
async def add_question_to_exam(
    exam_id: UUID,
    body: exam_schema.ExamQuestionCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    exam = await ExamService.select_exam(db, exam_id=exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    if exam.creator != current_user.id:
        raise HTTPException(status_code=403, detail="Not allowed")

    ids = await ExamService.add_questions_to_exam(db, exam=exam, question_ids=body.question_ids)
    await db.commit()
    return ids

@router.get("/content/{exam_id}", description="获取试卷详情", response_model=exam_schema.ExamPaper)
async def get_paper_content(
    exam_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    exam = await ExamService.get_exam_with_questions(db, exam_id=exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    # 一次联表查询题目，按关联表顺序返回
    questions = [exam_schema.PaperQuestionOut.model_validate({
        **pq.question.__dict__,
        "paper_question_id": pq.id
    }) for pq in exam.paper_questions]

    exam_data = exam_schema.ExamPaper.model_validate(exam)
    exam_data.questions = questions
    return exam_data

@router.get(
    "/list",
    description="查询指定教师的所有试卷（分页），返回总数并处理页码边界",
    response_model=exam_schema.PageOut,
)
async def list_teacher_exams(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    limit: int = Query(10, ge=1, le=100, description="每页数量"),
    page: int = Query(1, description="页码(从1开始，可小于1将被修正为1)"),
    sort_by: Literal["create_time", "difficulty"] = Query("create_time"),
    sort_order: Literal["asc", "desc"] = Query("desc"),
):
    # 总数统计 + 列表
    total, items = await ExamService.list_exams_by_creator(
        db,
        creator=current_user.id,
        limit=limit,
        offset=0,  # 将根据 page 计算
        sort_by=sort_by if sort_by in ("create_time", "difficulty") else "create_time",
        sort_order=sort_order if sort_order in ("asc", "desc") else "desc",
    )

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
    # 重新获取分页数据（复用服务层排序逻辑）
    total, items = await ExamService.list_exams_by_creator(
        db,
        creator=current_user.id,
        limit=limit,
        offset=offset,
        sort_by=sort_by if sort_by in ("create_time", "difficulty") else "create_time",
        sort_order=sort_order if sort_order in ("asc", "desc") else "desc",
    )
    return exam_schema.PageOut(
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
    response_model=exam_schema.CursorPage,
)
async def list_teacher_exams_cursor(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    limit: int = Query(10, ge=1, le=100),
    cursor: Optional[str] = Query(None, description="上一次响应返回的 next_cursor"),
):
    # 统计总数
    total = (await db.execute(select(func.count()).where(ExaminationInfo.creator == current_user.id))).scalar_one()

    last_time = last_id = None
    if cursor:
        last_time, last_id = _decode_cursor(cursor)

    rows = await ExamService.list_exams_cursor(
        db,
        creator=current_user.id,
        limit=limit,
        last_time=last_time,
        last_id=last_id,
    )

    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = None
    if has_more:
        last = items[-1]
        next_cursor = _encode_cursor(last.start_time, last.id)
    return exam_schema.CursorPage(items=items, next_cursor=next_cursor, total=total)



@router.get("/detail",description="获取某个时间段考试记录及相关人员信息",response_model=List[exam_schema.ExamDetail])
async def get_exam_details(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    start_time: datetime,
    end_time: datetime,
):
    exams = await ExamService.get_exam_detail_by_time(db, start_time=start_time, end_time=end_time)

    response = list(
        exam_schema.ExamDetail.model_validate({
            **exam.__dict__,
            "examinees": [
                exam_schema.StudentInfo.model_validate({
                    **examinee.student.__dict__,
                    "examinee_status": examinee.status
                }) for examinee in exam.examinees if examinee.student is not None
            ]
        }) for exam in exams
    )
    

    return response


@router.post("/join/{exam_id}",description="学生加入考试",response_model=List[exam_schema.ExamineeCreateOut])
async def student_join_exam(
    exam_id: UUID,
    body: List[UUID],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    if not body:
        return []

    examinees = await ExamService.insert_examinees(db, exam_id=exam_id, body=body)
    await db.commit()
    # 对每个对象单独refresh
    for examinee in examinees:
        await db.refresh(examinee)
    return [exam_schema.ExamineeCreateOut.model_validate(examinee) for examinee in examinees]





    
  