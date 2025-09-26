from datetime import datetime
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, Field,field_validator,field_serializer,model_validator
from app.user.schema import UserWithInfoOut
from app.question.schema import QuestionOut


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

    @model_validator(mode='after')
    def check_times(self):
        # 允许相等，且确保不为 None
        if self.start_time is None or self.end_time is None:
            raise ValueError("start_time and end_time are required")
        if self.end_time < self.start_time:
            raise ValueError("end_time must not be before start_time")
        return self

    @field_validator("start_time")
    def check_start_time(cls, v):
        # 去除时区信息
        if v.tzinfo:
            v = v.astimezone(tz=None).replace(tzinfo=None)
        # 放宽为允许等于当前时间，便于测试构造
        if v < datetime.now():
            raise ValueError("start_time must be now or in the future")
        return v

    @field_validator("end_time")
    def check_end_time(cls, v):
        # 去除时区信息
        if v.tzinfo:
            v = v.astimezone(tz=None).replace(tzinfo=None)
        return v

    @field_validator("duration")
    def check_duration(cls, v):
        if v <= 0:
            raise ValueError("duration must be positive")
        return v
    
    @model_validator(mode='after')
    def check_scores(self):
        if self.pass_score is not None and self.total_score is not None and self.pass_score > self.total_score:
            raise ValueError("pass_score cannot be greater than total_score")
        return self
    
    @field_validator("total_score")
    def check_total_score(cls, v):
        if v <= 0:
            raise ValueError("total_score must be positive")
        return v
    
    @field_validator("type")
    def check_type(cls, v):
        if v not in (1, 2, 3, 4, 5):
            raise ValueError("type must be one of 1, 2, 3, 4, 5")
        return v
    
    @field_validator("difficulty_level")
    def check_difficulty_level(cls, v):
        if v not in (1, 2, 3):
            raise ValueError("difficulty_level must be one of 1, 2, 3")
        return v
    
    @field_validator("grade_level")
    def check_grade_level(cls, v):
        if v not in (1, 2, 3, 4):
            raise ValueError("grade_level must be one of 1, 2, 3, 4")
        return v

    @field_serializer("start_time", "end_time")
    def serialize_datetime(self, v: datetime) -> str:
        if v and v.tzinfo:

            v = v.astimezone(tz=None).replace(tzinfo=None)
        return v.isoformat()


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

    @model_validator(mode='after')
    def check_times(self):
        # 仅在两者均提供时进行校验，并允许相等
        if self.start_time is not None and self.end_time is not None:
            if self.end_time < self.start_time:
                raise ValueError("end_time must not be before start_time")
        return self

    @field_validator("start_time")
    def check_start_time(cls, v):
        # 去除时区信息
        if v.tzinfo:
            v = v.astimezone(tz=None).replace(tzinfo=None)
        if v < datetime.now():
            raise ValueError("start_time must be now or in the future")
        return v

    @field_validator("end_time")
    def check_end_time(cls, v):
        # 去除时区信息
        if v.tzinfo:
            v = v.astimezone(tz=None).replace(tzinfo=None)
        return v

    @field_validator("duration")
    def check_duration(cls, v):
        if v <= 0:
            raise ValueError("duration must be positive")
        return v

    @model_validator(mode='after')
    def check_scores(self):
        if self.pass_score is not None and self.total_score is not None and self.pass_score > self.total_score:
            raise ValueError("pass_score cannot be greater than total_score")
        return self
    
    @field_validator("total_score")
    def check_total_score(cls, v):
        if v <= 0:
            raise ValueError("total_score must be positive")
        return v
    
    @field_validator("type")
    def check_type(cls, v):
        if v not in (1, 2, 3, 4, 5):
            raise ValueError("type must be one of 1, 2, 3, 4, 5")
        return v
    
    @field_validator("difficulty_level")
    def check_difficulty_level(cls, v):
        if v not in (1, 2, 3):
            raise ValueError("difficulty_level must be one of 1, 2, 3")
        return v
    
    @field_validator("grade_level")
    def check_grade_level(cls, v):
        if v not in (1, 2, 3, 4):
            raise ValueError("grade_level must be one of 1, 2, 3, 4")
        return v

    @field_validator("status")
    def check_status(cls, v):
        if v not in (1, 2):
            raise ValueError("status must be one of 1, 2")
        return v


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

class PaperQuestionOut(QuestionOut):
    paper_question_id: UUID

class ExamPaper(ExamOut):
    questions: List[PaperQuestionOut] = Field(default_factory=list)

class StudentInfo(UserWithInfoOut):
    submit_time: Optional[datetime] = None
    examinee_status: int = Field(1, description="0-未参加，1-已提交，2-缺考")

    @field_validator("submit_time")
    def check_submit_time(cls, v):
        # 去除时区信息
        if v and v.tzinfo:
            v = v.astimezone(tz=None).replace(tzinfo=None)
        return v


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

    class Config:
        from_attributes = True

class ExamQuestionCreate(BaseModel):
    question_ids: List[UUID]

class ExamineeCreateOut(BaseModel):
    exam_id: UUID
    student_id: UUID
    status: int
    submit_time: Optional[datetime] = None

    class Config:
        from_attributes = True
