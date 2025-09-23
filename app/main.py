from __future__ import annotations

from fastapi import FastAPI
from app.router.user import router as user_router
from app.router.examination import router as exam_router
from app.router.question import router as question_router

from app.config import get_settings
from app.db.base import Base
from app.db.session import engine
from app.db.redis import init_redis, close_redis


settings = get_settings()

app = FastAPI(title=settings.APP_NAME, debug=settings.DEBUG)
app.include_router(user_router)
app.include_router(exam_router)
app.include_router(question_router)
@app.on_event("startup")
async def on_startup() -> None:
    # For demo/dev: create tables automatically. In production, use Alembic migrations.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Init Redis
    await init_redis()

@app.on_event("shutdown")
async def on_shutdown() -> None:
    await close_redis()
@app.get("/health")
def health_check():
    return {"status": "ok"}
