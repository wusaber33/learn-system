from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from typing import AsyncGenerator
from app.config import get_settings


settings = get_settings()

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_size=10,
    max_overflow=30,
    pool_recycle=60 * 30,
)



async_session = sessionmaker(
    engine, expire_on_commit=False, class_=AsyncSession
)

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:  # type: ignore[func-returns-value]
        yield session
