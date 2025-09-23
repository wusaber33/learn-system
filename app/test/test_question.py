import unittest
from uuid import UUID, uuid4
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.db.db import User, UserInfo,Question
from app.router.user import get_password_hash

from app.test.client import get_client,_ensure_admin

ADMIN_NAME = "test_admin_ci"
ADMIN_PASS = "Admin#123456"

class TestDeleteQuestion(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = get_client()
  
    def _get_token(self, username: str, password: str) -> str:
        resp = self.client.post("/user/token", data={"username": username, "password": password})
        self.assertEqual(resp.status_code, 200, resp.text)
        token = resp.json().get("access_token")
        self.assertTrue(token)
        return token
    
    def test_delete_question_success(self):
        token = self._get_token(ADMIN_NAME, ADMIN_PASS)
        headers = {"Authorization": f"Bearer {token}"}

        # First, create a question to ensure there is something to delete
        question_data = {
            "content": "What is the capital of France?",
            "type": 1,
            "options": {"A": "Berlin", "B": "Madrid", "C": "Paris", "D": "Rome"},
            "answer": "C",
            "score": 5.0,
            "analysis": "The capital of France is Paris.",
            "level": 1
        }
        create_resp = self.client.post("/question", json=question_data, headers=headers)
        self.assertEqual(create_resp.status_code, 200, create_resp.text)
        created_question = create_resp.json()
        question_id = created_question["id"]

        # Now, delete the question
        delete_resp = self.client.delete(f"/question/{question_id}", headers=headers)
        self.assertEqual(delete_resp.status_code, 200, delete_resp.text)
        self.assertTrue(delete_resp.json().get("ok"))

        # Verify the question has been deleted by attempting to delete it again
        delete_again_resp = self.client.delete(f"/question/{question_id}", headers=headers)
        self.assertEqual(delete_again_resp.status_code, 404, delete_again_resp.text)
        self.assertEqual(delete_again_resp.json().get("detail"), "Question not found")

    def test_delete_question_unauthorized(self):
        # Attempt to delete a question without authentication
        question_id = str(uuid4())  # Random UUID, question likely doesn't exist
        delete_resp = self.client.delete(f"/question/{question_id}")
        self.assertEqual(delete_resp.status_code, 401, delete_resp.text)  # Unauthorized

    def test_delete_question_forbidden(self):
        # Create a non-admin user
        token = self._get_token(ADMIN_NAME, ADMIN_PASS)
        headers = {"Authorization": f"Bearer {token}"}

        uname = f"user_{uuid4().hex[:8]}"
        user_payload = {
            "name": uname,
            "password": "P@ssw0rd!",
            "role": 2,  # Regular user role
            "status": 1,
            "info": {
                "phone": "13800000000",
                "email": f"{uname}@example.com",
                "address": "Somewhere",
                "avatar": "http://img.example.com/a.png",
                "birthday": datetime(2000, 1, 2).isoformat(),
            },
        }
        resp = self.client.post("/user", json=user_payload, headers=headers)
        self.assertEqual(resp.status_code, 200, resp.text)
        user = resp.json()
        user_token = self._get_token(uname, "P@ssw0rd!")
        user_headers = {"Authorization": f"Bearer {user_token}"}
        # Attempt to delete a question as a non-admin user
        question_id = str(uuid4())  # Random UUID, question likely doesn't exist
        delete_resp = self.client.delete(f"/question/{question_id}", headers=user_headers)
        self.assertEqual(delete_resp.status_code, 403, delete_resp.text)  # Forbidden
        self.assertEqual(delete_resp.json().get("detail"), "Only teacher/admin can create questions")

    def test_delete_nonexistent_question(self):
        token = self._get_token(ADMIN_NAME, ADMIN_PASS)
        headers = {"Authorization": f"Bearer {token}"}

        # Attempt to delete a question that does not exist
        question_id = str(uuid4())  # Random UUID, question likely doesn't exist
        delete_resp = self.client.delete(f"/question/{question_id}", headers=headers)
        self.assertEqual(delete_resp.status_code, 404, delete_resp.text)  # Not Found
        self.assertEqual(delete_resp.json().get("detail"), "Question not found")       