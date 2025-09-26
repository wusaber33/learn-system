from __future__ import annotations

from fastapi import FastAPI
from app.user.view import router as user_router
from app.exam.view import router as exam_router
from app.question.view import router as question_router
from contextlib import asynccontextmanager
from app.config import get_settings
from app.cmn.base import Base
from app.cmn.session import engine
from app.cmn.redis import init_redis, close_redis


settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # For demo/dev: create tables automatically. In production, use Alembic migrations.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Init Redis
    await init_redis()
    yield
    await close_redis()

app = FastAPI(title=settings.APP_NAME, debug=settings.DEBUG,lifespan=lifespan)
app.include_router(user_router)
app.include_router(exam_router)
app.include_router(question_router)

@app.get("/health")
def health_check():
    return {"status": "ok"}
