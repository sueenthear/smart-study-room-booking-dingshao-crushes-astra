from __future__ import annotations

import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main as app_main


ADMIN_HEADERS = {"Authorization": "Bearer test-admin-token"}
STUDENT_HEADERS = {"Authorization": "Bearer test-student-token"}
OTHER_STUDENT_HEADERS = {"Authorization": "Bearer test-other-student-token"}


class SecurityAndConcurrencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.db_patch = patch.object(app_main, "DB_PATH", self.db_path)
        self.db_patch.start()
        self._reset_database()
        self.client = TestClient(app_main.app)
        self._seed_sessions()

    def tearDown(self) -> None:
        self.client.close()
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def _reset_database(self) -> None:
        if self.db_path.exists():
            self.db_path.unlink()
        app_main.init_db()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def _seed_sessions(self) -> None:
        now = int(app_main.time())
        db = self._connect()
        db.executemany(
            "INSERT INTO auth_sessions(token_hash, role, user_id, account, name, expires_at, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    app_main.token_digest("test-admin-token"),
                    "admin",
                    None,
                    "admin",
                    "林管理员",
                    now + 3600,
                    app_main.now_text(),
                ),
                (
                    app_main.token_digest("test-student-token"),
                    "student",
                    1,
                    "2024010201",
                    "林知夏",
                    now + 3600,
                    app_main.now_text(),
                ),
                (
                    app_main.token_digest("test-other-student-token"),
                    "student",
                    2,
                    "2024020816",
                    "周予安",
                    now + 3600,
                    app_main.now_text(),
                ),
            ],
        )
        db.commit()
        db.close()

    def _schedule(self, day: int) -> tuple[str, str]:
        return f"2031-02-{day:02d} 09:00", f"2031-02-{day:02d} 11:00"

    def test_login_creates_server_side_session(self) -> None:
        response = self.client.post(
            "/api/auth/login",
            json={"account": "admin", "password": "admin123456", "role": "admin"},
        )
        self.assertEqual(response.status_code, 200)
        token = response.json()["token"]
        identity = self.client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(identity.status_code, 200)
        self.assertEqual(identity.json()["role"], "admin")

        logout = self.client.post(
            "/api/auth/logout",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(logout.status_code, 200)
        expired = self.client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(expired.status_code, 401)

    def test_admin_mutations_require_authentication_and_role(self) -> None:
        start_at, end_at = self._schedule(1)
        admin_requests = [
            ("post", "/api/classrooms", {"name": "安全测试教室", "floor": "一层"}),
            ("patch", "/api/classrooms/1", {"name": "改名教室", "floor": "一层"}),
            ("delete", "/api/classrooms/1", None),
            ("patch", "/api/rooms/1/status", {"status": "maintenance", "note": "测试"}),
            (
                "post",
                "/api/users",
                {"name": "测试学生", "student_no": "2099000001", "phone": ""},
            ),
            (
                "patch",
                "/api/users/1",
                {"name": "林知夏", "student_no": "2024010201", "phone": ""},
            ),
            ("delete", "/api/users/1", None),
            ("post", "/api/violations", {"user_id": 1, "reason": "测试"}),
            ("patch", "/api/complaints/1", {"status": "已完成", "reply": "测试"}),
            ("get", "/api/users", None),
            ("get", "/api/overview", None),
            ("get", "/api/analytics", None),
        ]
        for method, url, payload in admin_requests:
            with self.subTest(url=url, role="anonymous"):
                response = self.client.request(method.upper(), url, json=payload)
                self.assertEqual(response.status_code, 401)
            with self.subTest(url=url, role="student"):
                response = self.client.request(
                    method.upper(), url, json=payload, headers=STUDENT_HEADERS
                )
                self.assertEqual(response.status_code, 403)

        response = self.client.post(
            "/api/bookings",
            json={"user_id": 1, "room_id": 1, "start_at": start_at, "end_at": end_at},
            headers=STUDENT_HEADERS,
        )
        self.assertEqual(response.status_code, 200)

    def test_admin_can_update_room_status(self) -> None:
        response = self.client.patch(
            "/api/rooms/1/status",
            json={"status": "maintenance", "note": "安全测试"},
            headers=ADMIN_HEADERS,
        )
        self.assertEqual(response.status_code, 200)
        db = self._connect()
        room = db.execute("SELECT status, status_note FROM rooms WHERE id = 1").fetchone()
        db.close()
        self.assertEqual((room["status"], room["status_note"]), ("maintenance", "安全测试"))

    def test_students_cannot_read_or_write_other_students_data(self) -> None:
        start_at, end_at = self._schedule(2)
        cases = [
            ("get", "/api/bookings?user_id=2", None),
            ("get", "/api/users/2/account-status", None),
            ("get", "/api/users/2/credit-profile", None),
            ("get", "/api/complaints?user_id=2", None),
            ("patch", "/api/bookings/2/status?status=cancelled", None),
            ("patch", "/api/users/2/password", {"old_password": "123456aa", "new_password": "abcdef"}),
        ]
        for method, url, payload in cases:
            with self.subTest(url=url):
                response = self.client.request(
                    method.upper(), url, json=payload, headers=STUDENT_HEADERS
                )
                self.assertEqual(response.status_code, 403)

        response = self.client.post(
            "/api/bookings",
            json={"user_id": 2, "room_id": 1, "start_at": start_at, "end_at": end_at},
            headers=STUDENT_HEADERS,
        )
        self.assertEqual(response.status_code, 200)
        db = self._connect()
        owner_id = db.execute(
            "SELECT user_id FROM bookings WHERE id = ?", (response.json()["id"],)
        ).fetchone()[0]
        db.close()
        self.assertEqual(owner_id, 1)

        response = self.client.post(
            "/api/complaints",
            json={"user_id": 2, "subject": "本人反馈", "content": "服务端应使用当前登录身份"},
            headers=STUDENT_HEADERS,
        )
        self.assertEqual(response.status_code, 200)
        db = self._connect()
        complaint_owner = db.execute(
            "SELECT user_id FROM complaints WHERE id = ?", (response.json()["id"],)
        ).fetchone()[0]
        db.close()
        self.assertEqual(complaint_owner, 1)

    def test_student_can_create_and_cancel_own_booking(self) -> None:
        start_at, end_at = self._schedule(3)
        response = self.client.post(
            "/api/bookings",
            json={"user_id": 2, "room_id": 1, "start_at": start_at, "end_at": end_at},
            headers=STUDENT_HEADERS,
        )
        self.assertEqual(response.status_code, 200)
        booking_id = response.json()["id"]
        db = self._connect()
        booking = db.execute(
            "SELECT user_id, source FROM bookings WHERE id = ?", (booking_id,)
        ).fetchone()
        db.close()
        self.assertEqual((booking["user_id"], booking["source"]), (1, "user"))

        response = self.client.patch(
            f"/api/bookings/{booking_id}/status?status=cancelled",
            headers=STUDENT_HEADERS,
        )
        self.assertEqual(response.status_code, 200)

    def test_concurrent_bookings_are_serialized(self) -> None:
        worker_count = 100
        barrier = threading.Barrier(worker_count)
        start_at, end_at = self._schedule(4)

        def attempt(index: int) -> int:
            client = TestClient(app_main.app)
            try:
                barrier.wait(timeout=30)
                response = client.post(
                    "/api/bookings",
                    json={
                        "user_id": 2,
                        "room_id": 1,
                        "start_at": start_at,
                        "end_at": end_at,
                    },
                    headers=STUDENT_HEADERS if index % 2 == 0 else OTHER_STUDENT_HEADERS,
                )
                return response.status_code
            finally:
                client.close()

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            results = list(executor.map(attempt, range(worker_count)))

        self.assertEqual(results.count(200), 1)
        self.assertEqual(results.count(409), worker_count - 1)
        db = self._connect()
        count = db.execute(
            "SELECT COUNT(*) FROM bookings "
            "WHERE room_id = 1 AND status IN ('booked', 'checked_in') "
            "AND start_at < ? AND end_at > ?",
            (end_at, start_at),
        ).fetchone()[0]
        db.close()
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
