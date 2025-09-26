from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis

from app.cmn.session import get_db
from app.cmn.db import UserGiftRecord
from app.cmn.redis import get_redis

router = APIRouter(prefix="/gift", tags=["gift"])

class ReceiveGiftRequest(BaseModel):
    request_id: UUID
    user_id: UUID

class ReceiveGiftResponse(BaseModel):
    success: bool
    message: str
    gift_id: str = None
    


async def check_user_is_new(db: AsyncSession, user_id: UUID) -> bool:
    """检查用户是否为新用户（注册时间在7天内且未参加过考试）"""
    # 实际业务中可能需要更复杂的逻辑
    return True

@router.post("/receive", response_model=ReceiveGiftResponse, description="领取新用户礼包")
async def receive_new_user_gift(
    req: ReceiveGiftRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
):  
    # 检查用户是否为新用户
    is_new_user = await check_user_is_new(db, req.user_id)
    if not is_new_user:
        return HTTPException(status_code=400, detail="User is not eligible for the gift")
    
    #  幂等性检查：通过request_id判断是否已处理过该请求
    cached_result = await redis.get(f"gift:request:{req.request_id}")
    if cached_result:
        if cached_result == b"success":
            return ReceiveGiftResponse(success=True, message="Gift already claimed", gift_id="gift123")
        else:
            raise HTTPException(status_code=400, detail="Gift already claimed")

    # 获取分布式锁，防止并发领取
    lock_key = f"lock:gift:{req.user_id}"
    # 尝试获取锁，过期时间10秒（防止死锁）
    lock_required = await redis.set(lock_key, "1", nx=True, ex=10)
    if not lock_required:
        raise HTTPException(status_code=429, detail="Too many requests, please try again later")
    
    try:
        # 检查用户是否已领取过礼包（数据库层面二次校验）
        result = await db.execute(
            "SELECT 1 FROM user_gift_record WHERE user_id = :user_id",
            {"user_id": req.user_id}
        )
        if result.scalar_one_or_none():
            # 已领取，记录request_id结果
            await redis.set(f"gift:request:{req.request_id}", "claimed", ex=3600*24)  # 记录已处理
            raise HTTPException(status_code=400, detail="Gift already claimed")

        # 发放礼包（实际业务中可能需要调用发放积分/优惠卷等逻辑）
        gift_id = "GIFT_NEW_USER_001"
         
         # 记录领取记录
        new_record = UserGiftRecord(
             user_id=req.user_id,
             gift_id=gift_id,
             request_id=req.request_id,
             receive_time=datetime.now()
         )
        db.add(new_record)
        await db.commit()

        # 缓存request_id处理结果
        await redis.set(f"gift:request:{req.request_id}", "success", ex=3600*24)  # 记录已处理，过期时间24小时

        return ReceiveGiftResponse(success=True, message="Gift claimed successfully", gift_id=gift_id)
    finally:
        # 释放锁
        await redis.delete(lock_key)



@router.post("/receive", response_model=ReceiveGiftResponse, description="抢数学资料")
async def receive_math_resource(
    req: ReceiveGiftRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
):  
    resource_id = "MATH_RESOURCE_001"
    #  幂等性检查：通过request_id判断是否已处理过该请求
    cached_result = await redis.get(f"resource:request:{req.request_id}")
    if cached_result:
        return {"success": False, "message": "Request already processed"}
    
    try:
        # 初始化Redis库存
        if not await redis.exists("resource:math_resource_stock"):
            await redis.set("resource:math_resource_stock", 100)  # 初始库存100份

        # 预减库存
        stock = await redis.decr("resource:math_resource_stock")

        # 库存是否充足
        # 如果库存小于0，表示没有库存了，回滚库存
        if stock < 0:
            await redis.incr("resource:math_resource_stock")  # 回滚库存
            return {"success": False, "message": "Out of stock"}

        #  持久化写入记录并扣减库存
        # 扣减库存，实际业务中可能需要更新数据库库存，要用乐观锁防止超领    
         
         # 记录领取记录
        new_record = UserGiftRecord(
             user_id=req.user_id,
             gift_id=resource_id,
             request_id=req.request_id,
             receive_time=datetime.now()
         )
        db.add(new_record)
        await db.commit()

        # 缓存request_id处理结果
        await redis.set(f"resource:request:{req.request_id}", "success", ex=60)  # 记录已处理，过期时间1分钟，1分钟基本抢完了

        return ReceiveGiftResponse(success=True, message="Resource claimed successfully", gift_id=resource_id)
    except Exception as e:
        # 出现异常，回滚库存
        await redis.incr("resource:math_resource_stock")
        await db.rollback()
        raise HTTPException(status_code=500, detail="Internal server error")      