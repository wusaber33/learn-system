from __future__ import annotations

from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base, TimestampMixin, UUID_PK, new_uuid7


# Users table with role
class User(TimestampMixin, Base):
    id: Mapped[uuid.UUID] = mapped_column(UUID_PK, primary_key=True, default=new_uuid7, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="student")  # "teacher" | "student"
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Relationships (virtual FKs via relationship only)
    profile: Mapped["UserProfile"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    exam_papers: Mapped[list["ExamPaper"]] = relationship(back_populates="teacher")
    attempts: Mapped[list["ExamAttempt"]] = relationship(back_populates="student")

    __table_args__ = (
        CheckConstraint("role in ('teacher','student')", name="ck_user_role"),
    )


class UserProfile(TimestampMixin, Base):
    id: Mapped[uuid.UUID] = mapped_column(UUID_PK, primary_key=True, default=new_uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID_PK, unique=True, index=True, nullable=False)
    bio: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    user: Mapped[User] = relationship(back_populates="profile", primaryjoin="UserProfile.user_id==User.id")


class ExamPaper(TimestampMixin, Base):
    id: Mapped[uuid.UUID] = mapped_column(UUID_PK, primary_key=True, default=new_uuid7)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    teacher_id: Mapped[uuid.UUID] = mapped_column(UUID_PK, index=True, nullable=False)

    teacher: Mapped[User] = relationship(back_populates="exam_papers", primaryjoin="ExamPaper.teacher_id==User.id")
    questions: Mapped[list["Question"]] = relationship(back_populates="paper", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_paper_teacher", "teacher_id"),
    )


class Question(TimestampMixin, Base):
    id: Mapped[uuid.UUID] = mapped_column(UUID_PK, primary_key=True, default=new_uuid7)
    paper_id: Mapped[uuid.UUID] = mapped_column(UUID_PK, index=True, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # simple single-choice example
    option_a: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    option_b: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    option_c: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    option_d: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    correct_option: Mapped[Optional[str]] = mapped_column(String(1), nullable=True)  # A/B/C/D

    paper: Mapped[ExamPaper] = relationship(back_populates="questions", primaryjoin="Question.paper_id==ExamPaper.id")

    __table_args__ = (
        CheckConstraint("correct_option in ('A','B','C','D')", name="ck_question_correct_option"),
        Index("ix_question_paper", "paper_id"),
    )


class ExamAttempt(TimestampMixin, Base):
    id: Mapped[uuid.UUID] = mapped_column(UUID_PK, primary_key=True, default=new_uuid7)
    paper_id: Mapped[uuid.UUID] = mapped_column(UUID_PK, index=True, nullable=False)
    student_id: Mapped[uuid.UUID] = mapped_column(UUID_PK, index=True, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    score: Mapped[Optional[float]] = mapped_column(nullable=True)

    paper: Mapped[ExamPaper] = relationship(back_populates="attempts", primaryjoin="ExamAttempt.paper_id==ExamPaper.id")
    student: Mapped[User] = relationship(back_populates="attempts", primaryjoin="ExamAttempt.student_id==User.id")
    answers: Mapped[list["ExamAnswer"]] = relationship(back_populates="attempt", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("paper_id", "student_id", name="uq_attempt_one_per_student_per_paper"),
        Index("ix_attempt_student", "student_id"),
        Index("ix_attempt_paper", "paper_id"),
    )


class ExamAnswer(TimestampMixin, Base):
    id: Mapped[uuid.UUID] = mapped_column(UUID_PK, primary_key=True, default=new_uuid7)
    attempt_id: Mapped[uuid.UUID] = mapped_column(UUID_PK, index=True, nullable=False)
    question_id: Mapped[uuid.UUID] = mapped_column(UUID_PK, index=True, nullable=False)
    selected_option: Mapped[Optional[str]] = mapped_column(String(1), nullable=True)

    attempt: Mapped[ExamAttempt] = relationship(
        back_populates="answers", primaryjoin="ExamAnswer.attempt_id==ExamAttempt.id"
    )
    question: Mapped[Question] = relationship(
        primaryjoin="ExamAnswer.question_id==Question.id"
    )

    __table_args__ = (
        CheckConstraint("selected_option in ('A','B','C','D')", name="ck_answer_selected_option"),
        Index("ix_answer_attempt", "attempt_id"),
        Index("ix_answer_question", "question_id"),
    )


# Back refs to complete relationships
ExamPaper.attempts = relationship("ExamAttempt", back_populates="paper")
