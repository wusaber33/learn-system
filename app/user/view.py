from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional, Literal
from uuid import UUID
import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis
from app.cmn.session import get_db
from app.cmn.db import User
from app.cmn.redis import get_redis
from app.user.schema import (
    SECRET_KEY,
    ALGORITHM,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    Token,
    TokenData,
    UserCreateWithInfo,
    UserUpdateWithInfo,
    UserWithInfoOut,
    UserWithInfoAndTotalPaper,
)
from app.user.service import UserService


# 注意：tokenUrl 必须与路由实际地址一致（用于 Swagger 登录）
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/user/token")

router = APIRouter(prefix="/user", tags=["user"])

# -------jwt auth utils ---------
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

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
        token_data = TokenData(user_id=UUID(str(user_id)), name=payload.get("name"), role=payload.get("role"))
    except jwt.InvalidTokenError:
        raise credentials_exception

    # 为了在依赖中返回 ORM 模型，这里直接从数据库读取实体
    user = await UserService._get_user_by_id(db, token_data.user_id)  # type: ignore[arg-type]
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
    user = await UserService.authenticate_user(db, form_data.username, form_data.password)
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
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
):
    new_user = await UserService.create_user(
        db, redis,
        name=payload.name,
        password=payload.password,
        role=payload.role,
        status=payload.status,
        creator=current_user.id,
        phone=payload.profile.phone,
        email=payload.profile.email,
        address=payload.profile.address or "",
        avatar=payload.profile.avatar or "",
        birthday=payload.profile.birthday,
    )
    response = UserWithInfoOut.model_validate(new_user)
    return response


@router.post("/admin", response_model=UserWithInfoOut)
async def create_user_admin(
    payload: UserCreateWithInfo,
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
):
    new_user = await UserService.create_user(
        db, redis,
        name=payload.name,
        password=payload.password,
        role=payload.role,
        status=payload.status,
        creator=None,
        phone=payload.profile.phone,
        email=payload.profile.email,
        address=payload.profile.address or "",
        avatar=payload.profile.avatar or "",
        birthday=payload.profile.birthday,
    )
    response = UserWithInfoOut.model_validate(new_user)
    return response



@router.get("",response_model=UserWithInfoOut)
async def get_user(
    user_id: UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
    cache_mode: Literal["string", "hash"] = "string",
):
    # 仅管理员/教师可以查看用户信息（按需调整）
    if int(current_user.role) not in (0, 1):
        raise HTTPException(status_code=403, detail="Only teacher/admin can view user profile")
    payload = await UserService.get_user(db, redis, user_id=user_id, cache_mode=cache_mode)
    return UserWithInfoOut.model_validate(payload)

@router.put("", response_model=UserWithInfoOut)
async def update_user(
    user_id: UUID,
    payload: UserUpdateWithInfo,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
):
    # 权限：管理员可改任意用户；否则仅允许本人修改
    if int(current_user.role) != 0 and current_user.id != user_id:
        raise HTTPException(status_code=403, detail="Not allowed to update this user")
    updated = await UserService.update_user(
        db, redis,
        user_id=user_id,
        name=payload.name,
        password=payload.password,
        role=payload.role,
        status=payload.status,
        phone=payload.profile.phone if payload.profile else None,
        email=payload.profile.email if payload.profile else None,
        address=payload.profile.address if payload.profile else None,
        avatar=payload.profile.avatar if payload.profile else None,
        birthday=payload.profile.birthday if payload.profile else None,
    )
    return UserWithInfoOut.model_validate(updated)

@router.delete("/cache/{user_id}")
async def invalidate_user_cache(
    user_id: UUID,
    redis: Annotated[Redis, Depends(get_redis)],
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    # 仅管理员可清除缓存（按需调整）
    if int(current_user.role) != 0:
        raise HTTPException(status_code=403, detail="Only admin can invalidate cache")
    await UserService.invalidate_user_cache(redis, user_id=user_id)
    return {"ok": True}

@router.delete("/{user_id}")
async def delete_user(
    user_id: UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
):
    # 仅管理员可删除用户（按需调整）
    if int(current_user.role) != 0:
        raise HTTPException(status_code=403, detail="Only admin can delete users")
    is_deleted = await UserService.delete_user(db, redis, delete_user_id=user_id, operator_id=current_user.id)
    if not is_deleted:
        raise HTTPException(status_code=404, detail="delete user error")
    return {"ok": True}

@router.get("/profile_and_totalpaper",response_model=UserWithInfoAndTotalPaper)
async def get_profile_and_totalpaper(
    userid: UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    user,total_paper = await UserService.get_user_with_totalpaper(db, user_id=userid)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.profile:
        raise HTTPException(status_code=404, detail="User profile not found")
    if not total_paper:
        total_paper = 0
    user_data = UserWithInfoOut.model_validate(user).model_dump()
    user_data['total_paper'] = total_paper
    response = UserWithInfoAndTotalPaper(**user_data)
    return response 

# ----- test compatibility helper -----
def get_password_hash(password: str) -> str:
    """Expose hashing for tests that previously imported from app.router.user"""
    return UserService.get_password_hash(password)