from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional, AsyncGenerator, Literal, Dict, Any
from uuid import UUID
import json

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy import select,func
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis

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


class UserInfoCreate(BaseModel):
    phone: str
    email: str
    address: Optional[str] = ""
    avatar: Optional[str] = ""
    birthday: Optional[datetime] = None


class UserInfoOut(BaseModel):
    phone: str
    email: str
    address: str
    avatar: str
    birthday: Optional[datetime] = None

    class Config:
        from_attributes = True


class UserCreateWithInfo(UserCreate):
    info: UserInfoCreate


class UserWithInfoOut(UserOut):
    info: UserInfoOut

class UserWithInfoAndTotalPaper(UserOut):
    info: UserInfoOut
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


class UserUpdateWithInfo(BaseModel):
    user: UserUpdate = UserUpdate()
    info: UserInfoUpdate = UserInfoUpdate()


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

async def get_userinfo_by_id(db: AsyncSession,user_id:UUID) -> Optional[UserInfo]:
    stmt = (
        select(UserInfo)
        .where(UserInfo.user_id == user_id)
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
    return f"user:{user_id}:info:v1"


def cache_key_user_hash(user_id: UUID) -> str:
    return f"user:{user_id}:info:hash:v1"

# 空值缓存 key
def cache_key_user_null(user_id: UUID) -> str:
    return f"user:{user_id}:info:null:v1"

def _serialize_user_payload(user: User, info: UserInfo) -> Dict[str, Any]:
    return {
        "id": str(user.id),
        "name": user.name,
        "role": int(user.role),
        "status": int(user.status),
        "info": {
            "phone": info.phone,
            "email": info.email,
            "address": info.address,
            "avatar": info.avatar,
            "birthday": info.birthday.isoformat() if info.birthday else None,
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
        "info_phone": payload["info"].get("phone") or "",
        "info_email": payload["info"].get("email") or "",
        "info_address": payload["info"].get("address") or "",
        "info_avatar": payload["info"].get("avatar") or "",
        "info_birthday": payload["info"].get("birthday") or "",
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
    info_birthday = mapping.get("info_birthday") or None
    try:
        birthday_parsed = datetime.fromisoformat(info_birthday) if info_birthday else None
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
        "info": {
            "phone": mapping.get("info_phone", ""),
            "email": mapping.get("info_email", ""),
            "address": mapping.get("info_address", ""),
            "avatar": mapping.get("info_avatar", ""),
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
    # 事务性创建（避免嵌套 begin：SQLAlchemy 2.0 默认会自动开启事务）
    try:
        hashed = get_password_hash(payload.password)
        new_user = User(
            name=payload.name,
            password=hashed,
            role=payload.role,
            status=payload.status,
            creator=current_user.id,
        )
        db.add(new_user)
        # 确保拿到 user.id
        await db.flush()

        info = payload.info
        new_info = UserInfo(
            user_id=new_user.id,
            phone=info.phone,
            email=info.email,
            address=info.address or "",
            avatar=info.avatar or "",
            birthday=info.birthday,
            status=1,
        )
        db.add(new_info)

        await db.commit()
    except Exception:
        await db.rollback()
        raise

    # 刷新对象
    await db.refresh(new_user)
    await db.refresh(new_info)

    # 维护ID集合，清空空值键
    try:
        await redis.sadd(KEY_USERS_SET, new_user.id)
        await redis.delete(cache_key_user_null(new_user.id))
    except Exception as e:
        pass


    return UserWithInfoOut(
        id=str(new_user.id),
        name=new_user.name,
        role=int(new_user.role),
        status=int(new_user.status),
        info=UserInfoOut(
            phone=new_info.phone,
            email=new_info.email,
            address=new_info.address,
            avatar=new_info.avatar,
            birthday=new_info.birthday,
        ),
    )

@router.post("/admin", response_model=UserWithInfoOut)
async def create_user(
    payload: UserCreateWithInfo,
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis,Depends(get_redis)]
):
    # 基础唯一性检查：用户名在未软删除用户中唯一
    db_user = await get_user_by_name(db, payload.name)
    if db_user:
        raise HTTPException(status_code=400, detail="Username already registered")
    # 事务性创建（避免嵌套 begin：SQLAlchemy 2.0 默认会自动开启事务）
    try:
        hashed = get_password_hash(payload.password)
        new_user = User(
            name=payload.name,
            password=hashed,
            role=payload.role,
            status=payload.status,
        )
        db.add(new_user)
        # 确保拿到 user.id
        await db.flush()

        info = payload.info
        new_info = UserInfo(
            user_id=new_user.id,
            phone=info.phone,
            email=info.email,
            address=info.address or "",
            avatar=info.avatar or "",
            birthday=info.birthday,
            status=1,
        )
        db.add(new_info)

        await db.commit()
    except Exception:
        await db.rollback()
        raise

    # 刷新对象
    await db.refresh(new_user)
    await db.refresh(new_info)

    # 维护ID集合，清空空值键
    try:
        await redis.sadd(KEY_USERS_SET, new_user.id)
        await redis.delete(cache_key_user_null(new_user.id))
    except Exception as e:
        pass


    return UserWithInfoOut(
        id=str(new_user.id),
        name=new_user.name,
        role=int(new_user.role),
        status=int(new_user.status),
        info=UserInfoOut(
            phone=new_info.phone,
            email=new_info.email,
            address=new_info.address,
            avatar=new_info.avatar,
            birthday=new_info.birthday,
        ),
    )



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
        raise HTTPException(status_code=403, detail="Only teacher/admin can view user info")
    
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
        info = cached["info"]
        return UserWithInfoOut(
            id=cached["id"],
            name=cached["name"],
            role=cached["role"],
            status=cached["status"],
            info=UserInfoOut(
                phone=info.get("phone", ""),
                email=info.get("email", ""),
                address=info.get("address", ""),
                avatar=info.get("avatar", ""),
                birthday=datetime.fromisoformat(info["birthday"]) if info.get("birthday") else None,
            ),
        )

    user = await get_user_by_id(db, user_id)
    userinfo = await get_userinfo_by_id(db, user_id)
    if not user or not userinfo:
        # 未找到，写入空值缓存（短TTL）并返回404
        await cache_mark_user_null(redis,user_id)
        raise HTTPException(status_code=404, detail="User not found")
    resp = UserWithInfoOut(
        id=str(user.id),
        name=user.name,
        role=int(user.role),
        status=int(user.status),
        info=UserInfoOut(
            phone=userinfo.phone,
            email=userinfo.email,
            address=userinfo.address,
            avatar=userinfo.avatar,
            birthday=userinfo.birthday,
        ),
    )
    # 回填缓存
    payload_dict = _serialize_user_payload(user, userinfo)
    if cache_mode == "hash":
        await cache_set_user_hash(redis, user.id, payload_dict)
    else:
        await cache_set_user_string(redis, user.id, payload_dict)

    try:
        await redis.sadd(KEY_USERS_SET, user.id)
    except Exception:
        pass

    return resp

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

    user = await get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    userinfo = await get_userinfo_by_id(db, user_id)
    if not userinfo:
        raise HTTPException(status_code=404, detail="User profile not found")

    try:
        # 用户名唯一性校验（若修改了 name）
        if payload.user.name and payload.user.name != user.name:
            stmt = (
                select(User)
                .where(User.name == payload.user.name)
                .where(User.deleted_at.is_(None))
                .limit(1)
            )
            existing = (await db.execute(stmt)).scalar_one_or_none()
            if existing and existing.id != user.id:
                raise HTTPException(status_code=400, detail="Username already registered")

        # 更新 User
        if payload.user.name is not None:
            user.name = payload.user.name
        if payload.user.password:
            user.password = get_password_hash(payload.user.password)
        if payload.user.role is not None:
            user.role = int(payload.user.role)
        if payload.user.status is not None:
            user.status = int(payload.user.status)

        # 更新 UserInfo（字段为 None 则不变）
        if payload.info.phone is not None:
            userinfo.phone = payload.info.phone
        if payload.info.email is not None:
            userinfo.email = payload.info.email
        if payload.info.address is not None:
            userinfo.address = payload.info.address
        if payload.info.avatar is not None:
            userinfo.avatar = payload.info.avatar
        if payload.info.birthday is not None:
            userinfo.birthday = payload.info.birthday

        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except Exception:
        await db.rollback()
        raise

    await db.refresh(user)
    await db.refresh(userinfo)

    # 同步缓存：先失效后重建两种结构
    await cache_invalidate_user(redis, user.id)
    payload_dict = _serialize_user_payload(user, userinfo)
    await cache_set_user_string(redis, user.id, payload_dict)
    await cache_set_user_hash(redis, user.id, payload_dict)

    return UserWithInfoOut(
        id=str(user.id),
        name=user.name,
        role=int(user.role),
        status=int(user.status),
        info=UserInfoOut(
            phone=userinfo.phone,
            email=userinfo.email,
            address=userinfo.address,
            avatar=userinfo.avatar,
            birthday=userinfo.birthday,
        ),
    )

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
        user.deleted_at = datetime.now()
        user.deleted_by = current_user.id
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

@router.get("/info_and_totalpaper",response_model=UserWithInfoAndTotalPaper)
async def get_info_and_totalpaper(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    userid: UUID = None,
):
    user = await get_user_by_id(db, userid)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    userinfo = await get_userinfo_by_id(db, userid)
    if not userinfo:
        raise HTTPException(status_code=404, detail="User profile not found")

    total_paper = await count_user_papers(db, userid)

    return UserWithInfoAndTotalPaper(
        id=str(user.id),
        name=user.name,
        role=int(user.role),
        status=int(user.status),
        info=UserInfoOut(
            phone=userinfo.phone,
            email=userinfo.email,
            address=userinfo.address,
            avatar=userinfo.avatar,
            birthday=userinfo.birthday,
        ),
        total_paper=total_paper
    )
