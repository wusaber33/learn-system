from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional, Literal, Dict, Any
from uuid import UUID
import json

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from passlib.context import CryptContext
from pydantic import BaseModel,field_validator,field_serializer
from sqlalchemy import select,func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from redis.asyncio import Redis
import re

from app.db.session import get_db
from app.db.db import User, UserInfo,ExaminationInfo
from app.db.redis import get_redis


# 为演示目的，密钥放在此处。生产请放入配置/环境变量。
SECRET_KEY = "94da9389d043d7563e4267705457d0de476c7c9df29f1672c80e93ce46778756"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30


# --------- Schemas ---------
class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    user_id: Optional[UUID] = None
    name: Optional[str] = None
    role: Optional[int] = None
    status: Optional[int] = None

class UserOut(BaseModel):
    id: UUID
    name: str
    role: int
    status: int

    class Config:
        from_attributes = True

class UserCreate(BaseModel):
    name: str
    password: str
    role: int = 1  # 0-管理员,1-教师,2-学生（与模型一致）
    status: int = 1  # 0-禁用,1-正常

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 6:
            raise ValueError("Password must be at least 6 characters")
        return v

    @field_validator('role')
    @classmethod
    def validate_role(cls, v: int) -> int:
        if v not in (0, 1, 2):
            raise ValueError("Role must be 0 (admin), 1 (teacher), or 2 (student)")
        return v
    
    @field_validator('status')
    @classmethod
    def validate_status(cls, v: int) -> int:
        if v not in (0, 1):
            raise ValueError("Status must be 0 (inactive) or 1 (active)")
        return v


class UserInfoCreate(BaseModel):
    phone: str
    email: str
    address: Optional[str] = ""
    avatar: Optional[str] = ""
    birthday: Optional[datetime] = None

    @field_validator('email')
    @classmethod
    def validate_email(cls, v: str) -> str:
        email_regex = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
        if not re.match(email_regex, v):
            raise ValueError("Invalid email format")
        return v

    @field_validator('phone')
    @classmethod
    def validate_phone(cls, v: str) -> str:
        phone_regex = r'^1[3-9]\d{9}$'
        if not re.match(phone_regex, v):
            raise ValueError("Invalid phone number format")
        return v

    @field_validator('birthday')
    @classmethod
    def validate_birthday(cls, v: Optional[datetime]) -> Optional[datetime]:
        # 去除时区
        if v:
            v = v.replace(tzinfo=None)
        if v and v > datetime.now():
            raise ValueError("Birthday cannot be in the future")
        return v


class UserInfoOut(BaseModel):
    phone: str
    email: str
    address: str
    avatar: str
    birthday: Optional[datetime] = None

    @field_serializer('birthday')
    def serialize_birthday(self, v: Optional[datetime]) -> Optional[str]:
        if v:
            return v.isoformat()
        return None
    
    @field_validator('birthday', mode='before')
    @classmethod
    def parse_birthday(cls, v):
        if isinstance(v, str):
            return datetime.fromisoformat(v)
        return v



    class Config:
        from_attributes = True


class UserCreateWithInfo(UserCreate):
    profile: UserInfoCreate


class UserWithInfoOut(UserOut):
    profile: UserInfoOut

class UserWithInfoAndTotalPaper(UserOut):
    profile: UserInfoOut
    total_paper: int = 0

# 更新用的可选字段模型
class UserUpdate(BaseModel):
    name: Optional[str] = None
    password: Optional[str] = None
    role: Optional[int] = None
    status: Optional[int] = None


class UserInfoUpdate(BaseModel):
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    avatar: Optional[str] = None
    birthday: Optional[datetime] = None


class UserUpdateWithInfo(UserUpdate):
    profile: UserInfoUpdate = UserInfoUpdate()


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# 注意：tokenUrl 必须与路由实际地址一致（用于 Swagger 登录）
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/user/token")

router = APIRouter(prefix="/user", tags=["user"])


# --------- Helpers ---------
def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)




async def get_user_by_name(db: AsyncSession, username: str) -> Optional[User]:
    stmt = (
        select(User)
        .where(User.name == username)
        .where(User.status == 1)
        .where(User.deleted_at.is_(None))
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, user_id: UUID) -> Optional[User]:
    stmt = (
        select(User)
        .where(User.id == user_id)
        .where(User.status == 1)
        .where(User.deleted_at.is_(None))
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()

async def get_users_with_profile(db: AsyncSession, user_id: UUID) -> Optional[User]:
    """单用户 + 预加载 profile (名称沿用, 但只支持单个用户以满足你的需求)"""
    stmt = (
        select(User)
        .options(selectinload(User.profile))
        .where(User.id == user_id)
        .where(User.status == 1)
        .where(User.deleted_at.is_(None))
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def authenticate_user(db: AsyncSession, username: str, password: str) -> Optional[User]:
    user = await get_user_by_name(db, username)
    if not user:
        return None
    if not verify_password(password, user.password):
        return None
    return user


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


# --------- Redis Cache Helpers ---------
TTL_SECONDS = 24 * 60 * 60  # 24小时

# 短TTL用于空值缓存
NULL_TTL_SECONDS =  60 # 1分钟
# ID 集合 key
KEY_USERS_SET = "users:ids:v1"

def cache_key_user_string(user_id: UUID) -> str:
    return f"user:{user_id}:profile:v1"


def cache_key_user_hash(user_id: UUID) -> str:
    return f"user:{user_id}:profile:hash:v1"

# 空值缓存 key
def cache_key_user_null(user_id: UUID) -> str:
    return f"user:{user_id}:profile:null:v1"

def _serialize_user_payload(user: User) -> Dict[str, Any]:
    profile = user.profile

    return {
        "id": str(user.id),
        "name": user.name,
        "role": int(user.role),
        "status": int(user.status),
        "profile": {
            "phone": getattr(profile, 'phone', ''),
            "email": getattr(profile, 'email', ''),
            "address": getattr(profile, 'address', ''),
            "avatar": getattr(profile, 'avatar', ''),
            "birthday": profile.birthday.isoformat() if (profile and profile.birthday) else None,
        },
    }


async def cache_set_user_string(redis: Redis, user_id: UUID, payload: Dict[str, Any]) -> None:
    await redis.set(cache_key_user_string(user_id), json.dumps(payload, ensure_ascii=False), ex=TTL_SECONDS)


async def cache_get_user_string(redis: Redis, user_id: UUID) -> Optional[Dict[str, Any]]:
    data = await redis.get(cache_key_user_string(user_id))
    if not data:
        return None
    try:
        return json.loads(data)
    except Exception:
        return None


async def cache_set_user_hash(redis: Redis, user_id: UUID, payload: Dict[str, Any]) -> None:
    key = cache_key_user_hash(user_id)
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


async def cache_get_user_hash(redis: Redis, user_id: UUID) -> Optional[Dict[str, Any]]:
    key = cache_key_user_hash(user_id)
    mapping = await redis.hgetall(key)
    if not mapping:
        return None
    # 恢复类型
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

async def count_user_papers(db: AsyncSession, user_id: UUID) -> int:
    stmt = (
        select(func.count())
        .select_from(ExaminationInfo)
        .where(ExaminationInfo.creator == user_id)
    )
    result = await db.execute(stmt)
    # 获取计数结果，scalar()会返回单个值
    return result.scalar()

async def cache_invalidate_user(redis: Redis, user_id: UUID) -> None:
    await redis.delete(cache_key_user_string(user_id))
    await redis.delete(cache_key_user_hash(user_id))
    # 删除空值缓存
    await redis.delete(cache_key_user_null(user_id))

# 空值缓存的读写
async def cache_mark_user_null(redis:Redis,user_id:UUID,ttl:int = NULL_TTL_SECONDS) -> None:
    # 存一个哨兵值，短TTL
    await redis.set(cache_key_user_null(user_id),"1",ex=ttl)

async def cache_is_user_null(redis:Redis,user_id: UUID) -> bool:
    return bool(await redis.exists(cache_key_user_null(user_id)))

# --------- Dependencies ---------
async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            raise credentials_exception
        token_data = TokenData(user_id=str(user_id), name=payload.get("name"), role=payload.get("role"))
    except jwt.InvalidTokenError:
        raise credentials_exception

    user = await get_user_by_id(db, token_data.user_id)  # type: ignore[arg-type]
    if user is None:
        raise credentials_exception
    return user


async def get_current_active_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    # status: 0-禁用,1-正常
    if current_user.status != 1:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


# --------- Routes ---------
@router.post("/token", response_model=Token)
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Token:
    user = await authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(user.id), "name": user.name, "role": int(user.role)},
        expires_delta=access_token_expires,
    )
    return Token(access_token=access_token, token_type="bearer")
    

@router.post("", response_model=UserWithInfoOut)
async def create_user(
    payload: UserCreateWithInfo,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    redis: Annotated[Redis,Depends(get_redis)]
):
    # 基础唯一性检查：用户名在未软删除用户中唯一
    db_user = await get_user_by_name(db, payload.name)
    if db_user:
        raise HTTPException(status_code=400, detail="Username already registered")
    try:
        hashed = get_password_hash(payload.password)
        new_user = User(
            name=payload.name,
            password=hashed,
            role=payload.role,
            status=payload.status,
            creator=current_user.id,
        )
        profile = payload.profile
        new_user.profile = UserInfo(
            phone=profile.phone,
            email=profile.email,
            address=profile.address or "",
            avatar=profile.avatar or "",
            birthday=profile.birthday,
            status=1,
        )
        db.add(new_user)
        await db.flush()
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    

    # 维护ID集合，清空空值键
    try:
        await redis.sadd(KEY_USERS_SET, new_user.id)
        await redis.delete(cache_key_user_null(new_user.id))
    except Exception:
        pass

    response = UserWithInfoOut.model_validate(new_user)
    return response


@router.post("/admin", response_model=UserWithInfoOut)
async def create_user_admin(
    payload: UserCreateWithInfo,
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis,Depends(get_redis)]
):
    # 基础唯一性检查：用户名在未软删除用户中唯一
    db_user = await get_user_by_name(db, payload.name)
    if db_user:
        raise HTTPException(status_code=400, detail="Username already registered")
    try:
        hashed = get_password_hash(payload.password)
        new_user = User(
            name=payload.name,
            password=hashed,
            role=payload.role,
            status=payload.status,
        )
        profile = payload.profile
        new_user.profile = UserInfo(
            phone=profile.phone,
            email=profile.email,
            address=profile.address or "",
            avatar=profile.avatar or "",
            birthday=profile.birthday,
            status=1,
        )
        db.add(new_user)
        await db.flush()
        await db.commit()
    except Exception:
        await db.rollback()
        raise


    # 维护ID集合，清空空值键
    try:
        await redis.sadd(KEY_USERS_SET, new_user.id)
        await redis.delete(cache_key_user_null(new_user.id))
    except Exception as e:
        pass

    response = UserWithInfoOut.model_validate(new_user)

    return response



@router.get("",response_model=UserWithInfoOut)
async def get_user(
    user_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    redis: Annotated[Redis, Depends(get_redis)],
    cache_mode: Literal["string", "hash"] = "string",
):
    # 仅管理员/教师可以查看用户信息（按需调整）
    if int(current_user.role) not in (0, 1):
        raise HTTPException(status_code=403, detail="Only teacher/admin can view user profile")
    
    # 空值缓存短路
    if await cache_is_user_null(redis,user_id):
        raise HTTPException(status_code=404, detail="User not found")
    
    # ID 集合快速判定（不存在则直接短路+标记为空）
    try:
        if not await redis.sismember(KEY_USERS_SET, user_id):
            await cache_mark_user_null(redis,user_id)
            raise HTTPException(status_code=404, detail="User not found")
    except Exception:
        pass    

    # 先从缓存中取，若取不到再查数据库并回填
    cached: Optional[Dict[str, Any]] = None
    if cache_mode == "hash":
        cached = await cache_get_user_hash(redis, user_id)
    else:
        cached = await cache_get_user_string(redis, user_id)

    if cached:
        return UserWithInfoOut.model_validate(cached)
        

    user = await get_users_with_profile(db, user_id)
    if not user:
        # 数据库确实不存在 -> 标记空值缓存
        try:
            await cache_mark_user_null(redis, user_id)
        except Exception:
            pass
        raise HTTPException(status_code=404, detail="User not found")

    # 回填缓存
    payload_dict = _serialize_user_payload(user)
    if cache_mode == "hash":
        await cache_set_user_hash(redis, user.id, payload_dict)
    else:
        await cache_set_user_string(redis, user.id, payload_dict)
    try:
        await redis.sadd(KEY_USERS_SET, user.id)
    except Exception:
        pass

    return UserWithInfoOut.model_validate(user)

@router.put("", response_model=UserWithInfoOut)
async def update_user(
    user_id: UUID,
    payload: UserUpdateWithInfo,
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    # 权限：管理员可改任意用户；否则仅允许本人修改
    if int(current_user.role) != 0 and current_user.id != user_id:
        raise HTTPException(status_code=403, detail="Not allowed to update this user")

    user = await get_users_with_profile(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.profile:
        raise HTTPException(status_code=404, detail="User profile not found")

    try:
        # 用户名唯一性校验（若修改了 name）
        if payload.name and payload.name != user.name:
            stmt = (
                select(User)
                .where(User.name == payload.name)
                .where(User.deleted_at.is_(None))
                .limit(1)
            )
            existing = (await db.execute(stmt)).scalar_one_or_none()
            if existing and existing.id != user.id:
                raise HTTPException(status_code=400, detail="Username already registered")

        # 更新 User（只改非 None 字段）
        if payload.name is not None:
            user.name = payload.name
        if payload.password:
            user.password = get_password_hash(payload.password)
        if payload.role is not None:
            user.role = int(payload.role)
        if payload.status is not None:
            user.status = int(payload.status)

        # 更新 UserInfo（字段为 None 则不变）
        if payload.profile.phone is not None:
            user.profile.phone = payload.profile.phone
        if payload.profile.email is not None:
            user.profile.email = payload.profile.email
        if payload.profile.address is not None:
            user.profile.address = payload.profile.address
        if payload.profile.avatar is not None:
            user.profile.avatar = payload.profile.avatar
        if payload.profile.birthday is not None:
            user.profile.birthday = payload.profile.birthday

        # flush 使改动落库但不触发 expire_on_commit 前的失效
        await db.flush()

        payload_dict = _serialize_user_payload(user)
        response_obj = UserWithInfoOut.model_validate(user)

        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except Exception:
        await db.rollback()
        raise

    await cache_invalidate_user(redis, user.id)
    await cache_set_user_string(redis, user.id, payload_dict)
    await cache_set_user_hash(redis, user.id, payload_dict)

    return response_obj

@router.delete("/cache/{user_id}")
async def invalidate_user_cache(
    user_id: UUID,
    redis: Annotated[Redis, Depends(get_redis)],
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    # 仅管理员可清除缓存（按需调整）
    if int(current_user.role) != 0:
        raise HTTPException(status_code=403, detail="Only admin can invalidate cache")
    await cache_invalidate_user(redis, user_id)
    return {"ok": True}

@router.delete("/{user_id}")
async def delete_user(
    user_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    # 仅管理员可删除用户（按需调整）
    if int(current_user.role) != 0:
        raise HTTPException(status_code=403, detail="Only admin can delete users")
    user = await get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    try:
        # 软删除
        user.soft_delete(current_user.id)
        await db.commit()
    except Exception:
        await db.rollback()
        raise    

    await cache_invalidate_user(redis, user.id)

    # 从ID集合以处并写入空值缓存短TTL
    try:
        await redis.srem(KEY_USERS_SET, user.id)
        await cache_mark_user_null(redis, user.id)
    except Exception:
        pass    
    return {"ok": True}

@router.get("/profile_and_totalpaper",response_model=UserWithInfoAndTotalPaper)
async def get_profile_and_totalpaper(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    userid: UUID,
):
    user = await get_users_with_profile(db, userid)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # 检查用户是否有profile信息
    if not user.profile:
        raise HTTPException(status_code=404, detail="User profile not found")

    total_paper = await count_user_papers(db, userid)

    user_data = UserWithInfoOut.model_validate(user).model_dump()
    user_data['total_paper'] = total_paper
    response = UserWithInfoAndTotalPaper(**user_data)

    return response 