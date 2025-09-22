from __future__ import annotations

from datetime import datetime
from typing import Callable
import uuid

try:
    # Prefer uuid7 from uuid6 package if available
    from uuid6 import uuid7 as _uuid7  # type: ignore
except Exception:  # pragma: no cover - fallback to time-based UUID1 if uuid6 missing
    def _uuid7() -> uuid.UUID:
        # Fallback: monotonic-ish UUID using uuid1; replace with uuid7 when available
        return uuid.uuid1()

from sqlalchemy.orm import DeclarativeBase, declared_attr, Mapped, mapped_column
from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID


class Base(DeclarativeBase):
    @declared_attr.directive
    def __tablename__(cls) -> str:  # type: ignore[override]
        return cls.__name__.lower()


def new_uuid7() -> uuid.UUID:
    """Generate a UUID7 value (fallback to uuid1 if uuid6 not installed)."""
    val = _uuid7()
    # Ensure we return stdlib uuid.UUID instance
    return uuid.UUID(str(val))


# Reusable column type for PostgreSQL UUID
UUID_PK = PG_UUID(as_uuid=True)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
