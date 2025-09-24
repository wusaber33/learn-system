import unittest
from uuid import UUID, uuid4
from datetime import datetime

from app.test.client import get_client

ADMIN_NAME = "test_admin_ci"
ADMIN_PASS = "Admin#123456"

class TestCreateUserIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = get_client()
    def _get_token(self, username: str, password: str) -> str:
        resp = self.client.post("/user/token", data={"username": username, "password": password})
        self.assertEqual(resp.status_code, 200, resp.text)
        token = resp.json().get("access_token")
        self.assertTrue(token)
        return token

    def test_create_user_success(self):
        token = self._get_token(ADMIN_NAME, ADMIN_PASS)
        headers = {"Authorization": f"Bearer {token}"}

        uname = f"user_{uuid4().hex[:8]}"
        payload = {
            "name": uname,
            "password": "P@ssw0rd!",
            "role": 1,
            "status": 1,
            "info": {
                "phone": "13800000000",
                "email": f"{uname}@example.com",
                "address": "Somewhere",
                "avatar": "http://img.example.com/a.png",
                # 传入 naive datetime 字符串，避免带时区与 DB 无时区列不匹配
                "birthday": datetime(2000, 1, 2).isoformat(),
            },
        }
        resp = self.client.post("/user", json=payload, headers=headers)
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertEqual(data["name"], uname)
        self.assertEqual(data["role"], 1)
        self.assertEqual(data["status"], 1)
        self.assertIn("info", data)
        self.assertEqual(data["info"]["phone"], "13800000000")
        self.assertEqual(data["info"]["email"], f"{uname}@example.com")
        _ = UUID(data["id"])

    def test_create_user_duplicate_name(self):
        token = self._get_token(ADMIN_NAME, ADMIN_PASS)
        headers = {"Authorization": f"Bearer {token}"}

        uname = f"user_{uuid4().hex[:8]}"
        payload = {
            "name": uname,
            "password": "P@ssw0rd!",
            "role": 1,
            "status": 1,
            "info": {
                "phone": "13900000000",
                "email": f"{uname}@example.com",
                "address": "",
                "avatar": "",
                "birthday": None,
            },
        }
        resp1 = self.client.post("/user", json=payload, headers=headers)
        self.assertEqual(resp1.status_code, 200, resp1.text)

        resp2 = self.client.post("/user", json=payload, headers=headers)
        self.assertEqual(resp2.status_code, 400, resp2.text)
        self.assertIn("Username already registered", resp2.text)