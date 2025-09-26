from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel,field_validator,field_serializer
import re

TTL_SECONDS = 24 * 60 * 60  # 24小时

# 短TTL用于空值缓存
NULL_TTL_SECONDS =  60 # 1分钟
# ID 集合 key
KEY_USERS_SET = "users:ids:v1"


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