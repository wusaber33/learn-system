'''
Author: wusaber33
Date: 2025-09-22 18:19:31
LastEditors: wusaber33
LastEditTime: 2025-09-22 19:57:11
FilePath: \learn-system\app\db\session.py
Description: 
Copyright (c) 2025 by wusaber33, All Rights Reserved. 
'''
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

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