from __future__ import annotations

from typing import AsyncGenerator, Optional

from redis.asyncio import Redis

from app.config import get_settings


_redis_client: Optional[Redis] = None


async def init_redis() -> Redis:
    """Initialize a singleton Redis client and verify the connection."""
    global _redis_client
    if _redis_client is None:
        settings = get_settings()
        _redis_client = Redis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,  # 返回 str，便于直接读写
        )
        # 简单连通性校验
        await _redis_client.ping()
    return _redis_client


async def get_redis() -> AsyncGenerator[Redis, None]:
    """FastAPI 依赖：按需获取全局 Redis 客户端（不在请求结束时关闭）。"""
    client = await init_redis()
    yield client


async def close_redis() -> None:
    """Gracefully close Redis client on application shutdown."""
    global _redis_client
    if _redis_client is not None:
        try:
            await _redis_client.aclose()
        finally:
            _redis_client = None
