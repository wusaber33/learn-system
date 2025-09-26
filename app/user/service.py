from uuid import UUID
from fastapi import   HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis
from datetime import datetime
import json
from typing import Optional, Literal, Dict, Any, Tuple
from passlib.context import CryptContext
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app.cmn.db import User, UserInfo, ExaminationInfo
from app.user.schema import TTL_SECONDS, NULL_TTL_SECONDS, KEY_USERS_SET


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _cache_key_user_string(user_id: UUID) -> str:
    return f"user:{user_id}:profile:v1"


def _cache_key_user_hash(user_id: UUID) -> str:
    return f"user:{user_id}:profile:hash:v1"


def _cache_key_user_null(user_id: UUID) -> str:
    return f"user:{user_id}:profile:null:v1"


def _serialize_user_payload(user: User) -> Dict[str, Any]:
    profile = user.profile
    return {
        "id": str(user.id),
        "name": user.name,
        "role": int(user.role),
        "status": int(user.status),
        "profile": {
            "phone": getattr(profile, "phone", ""),
            "email": getattr(profile, "email", ""),
            "address": getattr(profile, "address", ""),
            "avatar": getattr(profile, "avatar", ""),
            "birthday": profile.birthday.isoformat() if (profile and profile.birthday) else None,
        },
    }


class UserService:
    # ----- Auth helpers -----
    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        return pwd_context.verify(plain_password, hashed_password)

    @staticmethod
    def get_password_hash(password: str) -> str:
        return pwd_context.hash(password)

    @staticmethod
    async def authenticate_user(db: AsyncSession, username: str, password: str) -> Optional[User]:
        user = await UserService._get_user_by_name(db, username)
        if not user:
            return None
        if not UserService.verify_password(password, user.password):
            return None
        return user

    # ----- Core CRUD -----
    @staticmethod
    async def create_user(db: AsyncSession, redis: Redis, *, name: str, password: str, role: int, status: int,
                          creator: Optional[UUID], phone: str, email: str,
                          address: str = "", avatar: str = "", birthday: Optional[datetime] = None) -> User:
        # 唯一性检查
        exists = await UserService._get_user_by_name(db, name)
        if exists:
            raise HTTPException(status_code=400, detail="Username already registered")

        user = User(
            name=name,
            password=UserService.get_password_hash(password),
            role=role,
            status=status,
            creator=creator,
        )
        user.profile = UserInfo(
            phone=phone,
            email=email,
            address=address or "",
            avatar=avatar or "",
            birthday=birthday,
            status=1,
        )
        try:
            db.add(user)
            await db.flush()
            await db.commit()
        except Exception:
            await db.rollback()
            raise

        try:
            await redis.sadd(KEY_USERS_SET, user.id)
            await redis.delete(_cache_key_user_null(user.id))
        except Exception:
            pass
        return user

    @staticmethod
    async def get_user(db: AsyncSession, redis: Redis, *, user_id: UUID, cache_mode: Literal["string", "hash"] = "string") -> Dict[str, Any]:
        # 空值缓存短路
        if await UserService._cache_is_user_null(redis, user_id):
            raise HTTPException(status_code=404, detail="User not found")

        # ID 集合快速判定
        try:
            if not await redis.sismember(KEY_USERS_SET, user_id):
                await UserService._cache_mark_user_null(redis, user_id)
                raise HTTPException(status_code=404, detail="User not found")
        except Exception:
            pass

        # 读缓存
        cached: Optional[Dict[str, Any]] = None
        if cache_mode == "hash":
            cached = await UserService._cache_get_user_hash(redis, user_id)
        else:
            cached = await UserService._cache_get_user_string(redis, user_id)
        if cached:
            return cached

        # DB 加载
        user = await UserService._get_user_with_profile(db, user_id)
        if not user:
            try:
                await UserService._cache_mark_user_null(redis, user_id)
            except Exception:
                pass
            raise HTTPException(status_code=404, detail="User not found")

        payload = _serialize_user_payload(user)
        # 回填缓存
        try:
            if cache_mode == "hash":
                await UserService._cache_set_user_hash(redis, user.id, payload)
            else:
                await UserService._cache_set_user_string(redis, user.id, payload)
            await redis.sadd(KEY_USERS_SET, user.id)
        except Exception:
            pass
        return payload

    @staticmethod
    async def update_user(db: AsyncSession, redis: Redis, *, user_id: UUID, name: Optional[str] = None, password: Optional[str] = None,
                          role: Optional[int] = None, status: Optional[int] = None,
                          phone: Optional[str] = None, email: Optional[str] = None,
                          address: Optional[str] = None, avatar: Optional[str] = None,
                          birthday: Optional[datetime] = None) -> Dict[str, Any]:
        user = await UserService._get_user_with_profile(db, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        if not user.profile:
            raise HTTPException(status_code=404, detail="User profile not found")

        # 名称修改唯一性
        if name and name != user.name:
            exists = await UserService._get_user_by_name(db, name)
            if exists and exists.id != user.id:
                raise HTTPException(status_code=400, detail="Username already registered")

        if name is not None:
            user.name = name
        if password:
            user.password = UserService.get_password_hash(password)
        if role is not None:
            user.role = int(role)
        if status is not None:
            user.status = int(status)

        if phone is not None:
            user.profile.phone = phone
        if email is not None:
            user.profile.email = email
        if address is not None:
            user.profile.address = address
        if avatar is not None:
            user.profile.avatar = avatar
        if birthday is not None:
            user.profile.birthday = birthday

        try:
            await db.flush()
            payload = _serialize_user_payload(user)
            await db.commit()
        except HTTPException:
            await db.rollback()
            raise
        except Exception:
            await db.rollback()
            raise

        try:
            await UserService._cache_invalidate_user(redis, user.id)
            await UserService._cache_set_user_string(redis, user.id, payload)
            await UserService._cache_set_user_hash(redis, user.id, payload)
        except Exception:
            pass
        return payload

    @staticmethod
    async def delete_user(db: AsyncSession, redis: Redis, *, delete_user_id: UUID, operator_id: UUID) -> bool:
        user = await UserService._get_user_by_id(db, delete_user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        try:
            user.soft_delete(operator_id)
            await db.commit()
        except Exception:
            await db.rollback()
            raise
        try:
            await UserService._cache_invalidate_user(redis, user.id)
            await redis.srem(KEY_USERS_SET, user.id)
            await UserService._cache_mark_user_null(redis, user.id)
        except Exception:
            pass
        return True

    @staticmethod
    async def invalidate_user_cache(redis: Redis, *, user_id: UUID) -> None:
        await UserService._cache_invalidate_user(redis, user_id)

    @staticmethod
    async def get_user_with_totalpaper(db: AsyncSession, *, user_id: UUID) -> Tuple[User, int]:
        user = await UserService._get_user_with_profile(db, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        if not user.profile:
            raise HTTPException(status_code=404, detail="User profile not found")
        total = await UserService._count_user_papers(db, user_id)
        return user, int(total or 0)

    # ----- Low-level helpers -----
    @staticmethod
    async def _get_user_by_name(db: AsyncSession, username: str) -> Optional[User]:
        stmt = (
            select(User)
            .where(User.name == username)
            .where(User.status == 1)
            .where(User.deleted_at.is_(None))
            .limit(1)
        )
        return (await db.execute(stmt)).scalar_one_or_none()

    @staticmethod
    async def _get_user_by_id(db: AsyncSession, user_id: UUID) -> Optional[User]:
        stmt = (
            select(User)
            .where(User.id == user_id)
            .where(User.status == 1)
            .where(User.deleted_at.is_(None))
            .limit(1)
        )
        return (await db.execute(stmt)).scalar_one_or_none()

    @staticmethod
    async def _get_user_with_profile(db: AsyncSession, user_id: UUID) -> Optional[User]:
        stmt = (
            select(User)
            .options(selectinload(User.profile))
            .where(User.id == user_id)
            .where(User.status == 1)
            .where(User.deleted_at.is_(None))
            .limit(1)
        )
        return (await db.execute(stmt)).scalar_one_or_none()

    @staticmethod
    async def _count_user_papers(db: AsyncSession, user_id: UUID) -> int:
        stmt = select(func.count()).select_from(ExaminationInfo).where(ExaminationInfo.creator == user_id)
        return int((await db.execute(stmt)).scalar() or 0)

    # ----- Cache helpers -----
    @staticmethod
    async def _cache_set_user_string(redis: Redis, user_id: UUID, payload: Dict[str, Any]) -> None:
        await redis.set(_cache_key_user_string(user_id), json.dumps(payload, ensure_ascii=False), ex=TTL_SECONDS)

    @staticmethod
    async def _cache_get_user_string(redis: Redis, user_id: UUID) -> Optional[Dict[str, Any]]:
        data = await redis.get(_cache_key_user_string(user_id))
        if not data:
            return None
        try:
            return json.loads(data)
        except Exception:
            return None

    @staticmethod
    async def _cache_set_user_hash(redis: Redis, user_id: UUID, payload: Dict[str, Any]) -> None:
        key = _cache_key_user_hash(user_id)
        mapping = {
            "id": payload["id"],
            "name": payload["name"],
            "role": str(payload["role"]),
            "status": str(payload["status"]),
            "profile_phone": payload["profile"].get("phone") or "",
            "profile_email": payload["profile"].get("email") or "",
            "profile_address": payload["profile"].get("address") or "",
            "profile_avatar": payload["profile"].get("avatar") or "",
            "profile_birthday": payload["profile"].get("birthday") or "",
        }
        if mapping:
            await redis.hset(key, mapping=mapping)
            await redis.expire(key, TTL_SECONDS)

    @staticmethod
    async def _cache_get_user_hash(redis: Redis, user_id: UUID) -> Optional[Dict[str, Any]]:
        key = _cache_key_user_hash(user_id)
        mapping = await redis.hgetall(key)
        if not mapping:
            return None
        profile_birthday = mapping.get("profile_birthday") or None
        try:
            birthday_parsed = datetime.fromisoformat(profile_birthday) if profile_birthday else None
        except Exception:
            birthday_parsed = None
        try:
            role_val = int(mapping.get("role", 0))
        except Exception:
            role_val = 0
        try:
            status_val = int(mapping.get("status", 0))
        except Exception:
            status_val = 0
        return {
            "id": mapping.get("id"),
            "name": mapping.get("name", ""),
            "role": role_val,
            "status": status_val,
            "profile": {
                "phone": mapping.get("profile_phone", ""),
                "email": mapping.get("profile_email", ""),
                "address": mapping.get("profile_address", ""),
                "avatar": mapping.get("profile_avatar", ""),
                "birthday": birthday_parsed.isoformat() if birthday_parsed else None,
            },
        }

    @staticmethod
    async def _cache_invalidate_user(redis: Redis, user_id: UUID) -> None:
        await redis.delete(_cache_key_user_string(user_id))
        await redis.delete(_cache_key_user_hash(user_id))
        await redis.delete(_cache_key_user_null(user_id))

    @staticmethod
    async def _cache_mark_user_null(redis: Redis, user_id: UUID, ttl: int = NULL_TTL_SECONDS) -> None:
        await redis.set(_cache_key_user_null(user_id), "1", ex=ttl)

    @staticmethod
    async def _cache_is_user_null(redis: Redis, user_id: UUID) -> bool:
        return bool(await redis.exists(_cache_key_user_null(user_id)))
