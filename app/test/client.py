import atexit
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.cmn.db import User, UserInfo
from app.user.view import get_password_hash

ADMIN_NAME = "test_admin_ci"
ADMIN_PASS = "Admin#123456"

_client_cm = None
_client = None
_inited = False

def get_client() -> TestClient:
    """
    返回全局唯一的 TestClient，并保证已在应用事件循环内预置管理员账号。
    """
    global _client_cm, _client, _inited
    if _client is None:
        _client_cm = TestClient(app, raise_server_exceptions=True)
        _client = _client_cm.__enter__()
        # 在应用事件循环内进行 DB 预置（关键）
        _client.portal.call(_ensure_admin)
        # 进程退出时优雅关闭
        atexit.register(_shutdown)
        _inited = True
    return _client

def _shutdown():
    global _client_cm, _client
    if _client_cm is not None:
        _client_cm.__exit__(None, None, None)
        _client_cm = None
        _client = None

# 注意：通过 _portal.call 调用时，此方法在应用事件循环中执行
async def _ensure_admin():
    from app.cmn.session import async_session
    async with async_session() as db:  # type: ignore
        res = await db.execute(
            select(User).where(User.name == ADMIN_NAME).where(User.deleted_at.is_(None))
        )
        admin = res.scalar_one_or_none()
        if admin:
            return
        admin = User(
            name=ADMIN_NAME,
            password=get_password_hash(ADMIN_PASS),
            role=0,
            status=1,
            creator=None,
        )
        db.add(admin)
        await db.flush()
        profile = UserInfo(
            user_id=admin.id,
            phone="10000000000",
            email="admin@example.com",
            address="",
            avatar="",
            birthday=None,
            status=1,
        )
        db.add(profile)
        await db.commit()