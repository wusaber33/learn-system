from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import asyncio

from app.api import router as api_router
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import engine


settings = get_settings()

app = FastAPI(title=settings.APP_NAME, debug=settings.DEBUG)

# CORS
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=settings.BACKEND_CORS_ORIGINS,
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )


@app.on_event("startup")
async def on_startup() -> None:
    # For demo/dev: create tables automatically. In production, use Alembic migrations.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


app.include_router(api_router, prefix=settings.API_STR)


@app.get("/health")
def health_check():
    return {"status": "ok"}
