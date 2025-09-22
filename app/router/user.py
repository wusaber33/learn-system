from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional, AsyncGenerator
from uuid import UUID

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session
from app.db.db import User, UserInfo


# 为演示目的，密钥放在此处。生产请放入配置/环境变量。
SECRET_KEY = "94da9389d043d7563e4267705457d0de476c7c9df29f1672c80e93ce46778756"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30


# --------- Schemas ---------
class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    user_id: Optional[str] = None
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


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# 注意：tokenUrl 必须与路由实际地址一致（用于 Swagger 登录）
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/user/token")

router = APIRouter(prefix="/user", tags=["user"])


# --------- Helpers ---------
def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:  # type: ignore[func-returns-value]
        yield session


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


async def get_user_by_id(db: AsyncSession, user_id: str) -> Optional[User]:
    stmt = (
        select(User)
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
    

@router.post("/create", response_model=UserWithInfoOut)
async def create_user(
    payload: UserCreateWithInfo,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
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
