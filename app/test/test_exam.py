import unittest
from uuid import UUID, uuid4
from datetime import datetime

from sqlalchemy import select

from app.test.client import get_client,_ensure_admin

ADMIN_NAME = "test_admin_ci"
ADMIN_PASS = "Admin#123456"

class TestUpdateExamination(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = get_client()

    def _get_token(self, username: str, password: str) -> str:
        resp = self.client.post("/user/token", data={"username": username, "password": password})
        self.assertEqual(resp.status_code, 200, resp.text)
        token = resp.json().get("access_token")
        self.assertTrue(token)
        return token
    
    def test_update_examination_success(self):

        token = self._get_token(ADMIN_NAME, ADMIN_PASS)
        # First, create an examination to update
        create_resp = self.client.post(
            "/exam",
            json={
                "name": "Original Title",
                "start_time": datetime.now().isoformat(),
                "end_time": (datetime.now()).isoformat(),
                "duration": 60,
                "total_score": 100.0,
                "pass_score": 60.0,
                "creator": str(uuid4()),
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(create_resp.status_code, 200, create_resp.text)
        exam_id = create_resp.json().get("id")
        self.assertTrue(exam_id)

        # Now, update the examination
        update_resp = self.client.put(
            f"/exam/{exam_id}",
            json={
                "name": "Updated Title",
                "start_time": datetime.now().isoformat(),
                "end_time": (datetime.now()).isoformat(),
                "duration": 90,
                "total_score": 150.0,
                "pass_score": 90.0,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(update_resp.status_code, 200, update_resp.text)
        updated_exam = update_resp.json()
        self.assertEqual(updated_exam["name"], "Updated Title")
        self.assertEqual(updated_exam["duration"], 90)
        self.assertEqual(updated_exam["total_score"], 150.0)
        self.assertEqual(updated_exam["pass_score"], 90.0)

    def test_update_examination_not_found(self):
        token = self._get_token(ADMIN_NAME, ADMIN_PASS)
        non_existent_id = str(uuid4())
        update_resp = self.client.put(
            f"/exam/{non_existent_id}",
            json={
                "name": "Updated Title",
                "start_time": datetime.now().isoformat(),
                "end_time": (datetime.now()).isoformat(),
                "duration": 90,
                "total_score": 150.0,
                "pass_score": 90.0,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(update_resp.status_code, 404, update_resp.text)
        self.assertEqual(update_resp.json().get("detail"), "Exam not found")

    def test_update_examination_unauthorized(self):
        non_existent_id = str(uuid4())
        update_resp = self.client.put(
            f"/exam/{non_existent_id}",
            json={
                "name": "Updated Title",
                "start_time": datetime.now().isoformat(),
                "end_time": (datetime.now()).isoformat(),
                "duration": 90,
                "total_score": 150.0,
                "pass_score": 90.0,
            },
        )
        self.assertEqual(update_resp.status_code, 401, update_resp.text)  # Unauthorized
        self.assertEqual(update_resp.json().get("detail"), "Not authenticated")

    def test_update_examination_forbidden(self):
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
        # Attempt to update an examination as a non-admin user
        # First, create an examination to update
        create_resp = self.client.post(
            "/exam",
            json={
                "name": "Original Title",
                "start_time": datetime.now().isoformat(),
                "end_time": (datetime.now()).isoformat(),
                "duration": 60,
                "total_score": 100.0,
                "pass_score": 60.0,
                "creator": str(uuid4()),
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(create_resp.status_code, 200, create_resp.text)
        exam_id = create_resp.json().get("id")
        self.assertTrue(exam_id)
        update_resp = self.client.put(
            f"/exam/{exam_id}",
            json={
                "name": "Updated Title",
                "start_time": datetime.now().isoformat(),
                "end_time": (datetime.now()).isoformat(),
                "duration": 90,
                "total_score": 150.0,
                "pass_score": 90.0,
            },
            headers=user_headers
        )
        self.assertEqual(update_resp.status_code, 403, update_resp.text)  # Forbidden
        self.assertEqual(update_resp.json().get("detail"), "Not allowed")
    
        
class TestListTeacherExam(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = get_client()

    def _get_token(self, username: str, password: str) -> str:
        resp = self.client.post("/user/token", data={"username": username, "password": password})
        self.assertEqual(resp.status_code, 200, resp.text)
        token = resp.json().get("access_token")
        self.assertTrue(token)
        return token

    def test_list_teacher_exams_success(self):
        token = self._get_token(ADMIN_NAME, ADMIN_PASS)
        headers = {"Authorization": f"Bearer {token}"}

        # Create a teacher user
        uname = f"teacher_{uuid4().hex[:8]}"
        user_payload = {
            "name": uname,
            "password": "P@ssw0rd!",
            "role": 1,  # Teacher role
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
        teacher = resp.json()
        teacher_id = teacher["id"]
        teacher_token = self._get_token(uname, "P@ssw0rd!")
        teacher_headers = {"Authorization": f"Bearer {teacher_token}"}
        # Create some exams for the teacher
        for i in range(3):
            exam_payload = {
                "name": f"Exam {i+1}",
                "type": 1,
                "start_time": datetime.now().isoformat(),
                "end_time": (datetime.now()).isoformat(),
                "difficulty_level": 1,
                "grade_level": 1,
                "duration": 60 + i * 10,
                "total_score": 100.0 + i * 10,
                "pass_score": 60.0 + i * 5,
            }
            create_resp = self.client.post("/exam", json=exam_payload, headers=teacher_headers)
            self.assertEqual(create_resp.status_code, 200, create_resp.text)
        # List exams for the teacher
        list_resp = self.client.get(f"/exam/list", headers=teacher_headers) 
        self.assertEqual(list_resp.status_code, 200, list_resp.text)
        pageout = list_resp.json()
        exams = pageout.get("items", [])
        self.assertIsInstance(exams, list)
        self.assertGreaterEqual(len(exams), 3)
        for exam in exams:
            self.assertEqual(exam["creator"], teacher_id)
            self.assertIn("name", exam)
            self.assertIn("type", exam)
            self.assertIn("difficulty_level", exam)
            self.assertIn("grade_level", exam)
            self.assertIn("start_time", exam)
            self.assertIn("end_time", exam)
            self.assertIn("duration", exam)
            self.assertIn("total_score", exam)
            self.assertIn("pass_score", exam)
            self.assertIn("creator", exam)
            self.assertIn("id", exam)
            _ = UUID(exam["id"])
            self.assertIn("status", exam)
        self.assertEqual(pageout.get("total"), 3)
        self.assertEqual(pageout.get("page"), 1)
        self.assertEqual(pageout.get("page_size"), 10)

    def test_list_teacher_exams_unauthorized(self):
        list_resp = self.client.get(f"/exam/list")
        self.assertEqual(list_resp.status_code, 401, list_resp.text)  # Unauthorized
        self.assertEqual(list_resp.json().get("detail"), "Not authenticated")

    def test_list_teacher_exams_invalid_page(self):
        token = self._get_token(ADMIN_NAME, ADMIN_PASS)
        headers = {"Authorization": f"Bearer {token}"}
        list_resp = self.client.get(f"/exam/list?page=0", headers=headers)
        self.assertEqual(list_resp.status_code, 422, list_resp.text)
        self.assertIn("ensure this value is greater than or equal to 1", list_resp.text)
