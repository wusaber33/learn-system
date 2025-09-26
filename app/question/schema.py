from typing import Any, Optional
from uuid import UUID
from datetime import datetime

from sqlalchemy import select
from pydantic import BaseModel, Field

from app.cmn.session import get_db

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
