from datetime import datetime
import time
import uuid
import random

from sqlalchemy import (
    Column,
    String,
    Integer,
    SmallInteger,
    Boolean,
    DateTime,
    Float,
    Text,
    UniqueConstraint,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID, JSONB
from sqlalchemy.orm import relationship
from app.db.base import Base
from typing import Optional


# ---- UUIDv7 生成器（优先使用 Python 3.12+ 或 uuid6 库，最后降级为 uuid4 时间有序替代） ----
def generate_uuid7() -> uuid.UUID:
    """生成 UUIDv7。

    优先使用:
    - Python 3.12+ 的 uuid.uuid7
    - 第三方库 uuid6.uuid7
    退化方案:
    - 近似时间有序的 UUID（非标准 v7，仅作为兜底，不建议用于严格依赖 v7 的场景）
    """
    # Python 3.12+
    if hasattr(uuid, "uuid7"):
        return uuid.uuid7()
    # uuid6 库
    try:
        from uuid6 import uuid7 as _uuid7  # type: ignore

        return _uuid7()
    except Exception:
        # 兜底：构造一个带毫秒时间熵的 UUID4 变体（不完全符合 v7 标准）
        # 提示：生产环境建议升级 Python 至 3.12+ 或安装 uuid6 库
        ts_ms = int(time.time() * 1000) & 0xFFFFFFFF
        rand = random.getrandbits(96)
        high = ts_ms << 96
        val = high | rand
        return uuid.UUID(int=val)

# 1. 创建一个与数据库对应的模型类对象
class User(Base):
    """用户表模型（教师/学生/管理员）"""

    __tablename__ = "t_user"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=generate_uuid7, comment="主键UUIDv7")
    name = Column(String(50), nullable=False, comment="姓名")
    password = Column(String(128), nullable=False, comment="密码（bcrypt哈希）")
    role = Column(SmallInteger, default=1, nullable=False, comment="0-管理员，1-教师，2-学生")
    sex = Column(Boolean, default=True, nullable=False,comment="True-男，False-女")
    age = Column(SmallInteger, nullable=True, comment="年龄")
    status = Column(SmallInteger, default=1, nullable=False, comment="0-禁用,1-正常")
    creator = Column(PGUUID(as_uuid=True), nullable=True, comment="创建人")
    create_time = Column(DateTime, default=datetime.now, nullable=False, comment="创建时间")
    update_time = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间")
    # 软删除字段（仅对 User 生效）
    deleted_at = Column(DateTime, index=True, nullable=True, comment="软删除时间，NULL=未删除")
    deleted_by = Column(PGUUID(as_uuid=True), nullable=True, comment="软删除操作者ID")

    # 关系（虚拟外键，无数据库级 FK）
    profile = relationship(
        "UserInfo",
        primaryjoin="User.id==foreign(UserInfo.user_id)",
        back_populates="user",
        uselist=False,
    )

    # 教师创建的试卷（ExaminationInfo）一对多
    exams_created = relationship(
        "ExaminationInfo",
        primaryjoin="User.id==foreign(ExaminationInfo.creator)",
        back_populates="creator_user",
    )

    # 学生参加的考试（Examinee）一对多
    exam_participations = relationship(
        "Examinee",
        primaryjoin="User.id==foreign(Examinee.student_id)",
        back_populates="student",
    )

    def __repr__(self):
        return f"<{self.__class__.__name__} {self.name}>"

    def soft_delete(self, by: Optional[uuid.UUID] = None, when: Optional[datetime] = None) -> None:
        """将用户标记为软删除。仅标记，不删除其关联数据。"""
        when = when or datetime.now()
        self.deleted_at = when
        if by is not None:
            self.deleted_by = by
    
class UserInfo(Base):
    """用户详细档案（一对一，主键即 user_id）"""

    __tablename__ = "t_user_info"

    user_id = Column(PGUUID(as_uuid=True), primary_key=True, comment="用户ID（虚拟外键->User.id）")
    phone = Column(String(20), nullable=False, comment="手机号")
    email = Column(String(100), nullable=False, comment="邮箱")
    address = Column(String(200), default="", nullable=False, comment="联系地址")
    avatar = Column(String(200), default="", nullable=False, comment="头像URL")
    birthday = Column(DateTime, comment="生日")
    status = Column(SmallInteger, default=1, nullable=False, comment="状态：0-禁用,1-正常")
    creator = Column(PGUUID(as_uuid=True), nullable=True, comment="创建人")
    create_time = Column(DateTime, default=datetime.now, nullable=False, comment="创建时间")
    update_time = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False, comment="更新时间")

    # 关系
    user = relationship(
        "User",
        primaryjoin="User.id==foreign(UserInfo.user_id)",
        back_populates="profile",
        uselist=False,
    )

    def __repr__(self):
        return f"<{self.__class__.__name__} {self.user_id}>"
    
class Question(Base):
    """题目表模型"""

    __tablename__ = "t_question"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=generate_uuid7, comment="主键UUIDv7")
    content = Column(Text, nullable=False, comment="题干")
    type = Column(SmallInteger, default=1, nullable=False, comment="1-单选，2-多选，3-判断")
    options = Column(JSONB, nullable=False, comment="选项（JSONB）")
    answer = Column(JSONB, nullable=False, comment="正确答案（JSONB）")
    score = Column(Float, default=1, nullable=False, comment="分值")
    analysis = Column(Text, default="", nullable=False, comment="解析")
    level = Column(SmallInteger, default=1, nullable=False, comment="1-简单，2-中等，3-困难")
    creator = Column(PGUUID(as_uuid=True), nullable=False, index=True, comment="虚拟外键->User.id(出题人)")
    create_time = Column(DateTime, default=datetime.now, nullable=False, comment="创建时间")
    update_by = Column(PGUUID(as_uuid=True), nullable=True, index=True, comment="虚拟外键->User.id")
    update_time = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False, comment="更新时间")
    status = Column(SmallInteger, default=1, nullable=False, comment="状态：0-禁用,1-正常")

    # 与试卷的关联对象列表
    question_papers = relationship(
        "PaperQuestion",
        primaryjoin="Question.id==foreign(PaperQuestion.question_id)",
        back_populates="question",
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        return f"<{self.__class__.__name__} {self.content[:20] if self.content else ''}>"

class ExaminationInfo(Base):
    """试卷/考试信息表模型（教师创建，一对多）"""

    __tablename__ = "t_examination_info"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=generate_uuid7, comment="主键UUIDv7")
    name = Column(String(100), nullable=False, index=True, comment="试卷/考试名称")
    type = Column(SmallInteger, default=1, nullable=False, comment="1-期中，2-期末，3-模拟，4-竞赛，5-练习", index=True)
    difficulty_level = Column(SmallInteger, default=1, nullable=False, comment="1-简单，2-中等，3-困难")
    grade_level = Column(SmallInteger, default=1, nullable=False, comment="1-小学，2-初中，3-高中，4-大学")
    total_score = Column(Float, default=100, nullable=False, comment="总分")
    pass_score = Column(Float, default=60, nullable=False, comment="及格分")
    duration = Column(Integer, default=90, nullable=False, comment="考试时长（分钟）")
    creator = Column(PGUUID(as_uuid=True), nullable=False, index=True, comment="虚拟外键->User.id(教师)")
    create_time = Column(DateTime, default=datetime.now, nullable=False, comment="创建时间")
    update_by = Column(PGUUID(as_uuid=True), nullable=True, index=True, comment="更新人ID")
    update_time = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False, comment="更新时间")
    start_time = Column(DateTime, nullable=False, comment="考试开始时间")
    end_time = Column(DateTime, nullable=False, comment="考试结束时间")
    status = Column(SmallInteger, default=1, nullable=False, comment="0-未发布,1-发布未开始,2-进行中,3-已结束,4-已取消")

    # 关系：创建者（教师）
    creator_user = relationship(
        "User",
        primaryjoin="User.id==foreign(ExaminationInfo.creator)",
        back_populates="exams_created",
        uselist=False,
    )

    # 关系：关联题目（通过关联对象 PaperQuestion）
    paper_questions = relationship(
        "PaperQuestion",
        primaryjoin="ExaminationInfo.id==foreign(PaperQuestion.examination_info_id)",
        back_populates="examination_info",
        cascade="all, delete-orphan",
    )

    # 关系：参加考试的学生（Examinee）
    examinees = relationship(
        "Examinee",
        primaryjoin="ExaminationInfo.id==foreign(Examinee.exam_id)",
        back_populates="exam",
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        return f"<{self.__class__.__name__} {self.name}>"

class PaperQuestion(Base):
    """试卷-题目 关联表（关联对象）"""

    __tablename__ = "t_paper_question"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=generate_uuid7, comment="主键UUIDv7")
    examination_info_id = Column(PGUUID(as_uuid=True), nullable=False, index=True, comment="虚拟外键->ExaminationInfo.id")
    question_id = Column(PGUUID(as_uuid=True), nullable=False, index=True, comment="虚拟外键->Question.id")
    creator = Column(PGUUID(as_uuid=True), nullable=True, index=True, comment="创建人ID")
    create_time = Column(DateTime, default=datetime.now, nullable=False, comment="创建时间")
    update_by = Column(PGUUID(as_uuid=True), nullable=True, index=True, comment="更新人ID")
    update_time = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False, comment="更新时间")
    status = Column(SmallInteger, default=1, nullable=False, comment="状态：0-禁用,1-正常")

    __table_args__ = (
        UniqueConstraint("examination_info_id", "question_id", name="uq_paper_question"),
        Index("ix_paper_question_paper_question", "examination_info_id", "question_id"),
    )

    # 关系
    examination_info = relationship(
        "ExaminationInfo",
        primaryjoin="ExaminationInfo.id==foreign(PaperQuestion.examination_info_id)",
        back_populates="paper_questions",
        uselist=False,
    )
    question = relationship(
        "Question",
        primaryjoin="Question.id==foreign(PaperQuestion.question_id)",
        back_populates="question_papers",
        uselist=False,
    )

    def __repr__(self):
        return f"<{self.__class__.__name__} {self.examination_info_id}-{self.question_id}>"
    
class Examinee(Base):
    """考试-学生 关联表（学生参加一次考试的记录）"""

    __tablename__ = "t_examinee"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=generate_uuid7, comment="主键UUIDv7")
    exam_id = Column(PGUUID(as_uuid=True), nullable=False, index=True, comment="虚拟外键->ExaminationInfo.id")
    student_id = Column(PGUUID(as_uuid=True), nullable=False, index=True, comment="虚拟外键->User.id(学生)")
    status = Column(SmallInteger, default=0, nullable=False, comment="0-未参加，1-已提交，2-缺考")
    submit_time = Column(DateTime, comment="提交时间")
    creator = Column(PGUUID(as_uuid=True), nullable=True, index=True, comment="创建人ID")
    create_time = Column(DateTime, default=datetime.now, nullable=False, comment="创建时间")
    update_by = Column(PGUUID(as_uuid=True), nullable=True, index=True, comment="更新人ID")
    update_time = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False, comment="更新时间")

    __table_args__ = (
        UniqueConstraint("exam_id", "student_id", name="uq_examinee_exam_student"),
    )

    # 关系
    exam = relationship(
        "ExaminationInfo",
        primaryjoin="ExaminationInfo.id==foreign(Examinee.exam_id)",
        back_populates="examinees",
        uselist=False,
    )
    student = relationship(
        "User",
        primaryjoin="User.id==foreign(Examinee.student_id)",
        back_populates="exam_participations",
        uselist=False,
    )

    # 学生的题目作答
    answers = relationship(
        "StudentAnswer",
        primaryjoin="Examinee.id==foreign(StudentAnswer.examinee_id)",
        back_populates="examinee",
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        return f"<{self.__class__.__name__} {self.exam_id}-{self.student_id}>"
    
class StudentAnswer(Base):
    """学生作答表（一次考试的一道题的答案与得分）"""

    __tablename__ = "t_student_answer"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=generate_uuid7, comment="主键UUIDv7")
    examinee_id = Column(PGUUID(as_uuid=True), nullable=False, index=True, comment="虚拟外键->Examinee.id")
    question_id = Column(PGUUID(as_uuid=True), nullable=False, index=True, comment="虚拟外键->Question.id")
    answers = Column(JSONB, nullable=False, comment="作答内容（JSONB）")
    score = Column(Float, default=0, nullable=False, comment="得分")
    submit_time = Column(DateTime, default=datetime.now, nullable=False, comment="提交时间")
    status = Column(SmallInteger, default=1, nullable=False, comment="状态：0-禁用,1-正常")

    __table_args__ = (
        UniqueConstraint("examinee_id", "question_id", name="uq_answer_examinee_question"),
    )

    # 关系
    examinee = relationship(
        "Examinee",
        primaryjoin="Examinee.id==foreign(StudentAnswer.examinee_id)",
        back_populates="answers",
        uselist=False,
    )
    question = relationship(
        "Question",
        primaryjoin="Question.id==foreign(StudentAnswer.question_id)",
        uselist=False,
    )

    def __repr__(self):
        return f"<{self.__class__.__name__} {self.examinee_id}>"
    

class UserGiftRecord(Base):
    """新用户注册礼包领取记录表"""
    __tablename__ = "user_gift_record"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), comment="记录ID")
    user_id = Column(String(36), nullable=False, index=True, comment="用户ID")
    gift_id = Column(String(36), nullable=False, comment="礼包ID")
    receive_time = Column(DateTime, default=datetime.utcnow, comment="领取时间")
    is_valid = Column(Boolean, default=True, comment="是否有效")
    request_id = Column(String(64), unique=True, comment="请求唯一标识（用于幂等性）")
    
    __table_args__ = (
        UniqueConstraint("user_id", name="uk_user_id"),
        {"comment": "新用户注册礼包领取记录"}
    )