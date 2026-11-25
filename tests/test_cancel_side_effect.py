from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main as app_main


STUDENT_HEADERS = {"Authorization": "Bearer test-student-token"}
OTHER_STUDENT_HEADERS = {"Authorization": "Bearer test-other-student-token"}


class CancelSideEffectTests(unittest.TestCase):
    """P1：取消未来预约不得释放正在被使用的座位。"""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.db_patch = patch.object(app_main, "DB_PATH", self.db_path)
        self.db_patch.start()
        app_main.init_db()
        self.client = TestClient(app_main.app)
        self._seed_sessions()

    def tearDown(self) -> None:
        self.client.close()
        self.db_patch.stop()
        self.temp_dir.cleanup()

    # ---- 夹具 ----
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
                (app_main.token_digest("test-student-token"), "student", 1, "2024010201", "林知夏",
                 now + 3600, app_main.now_text()),
                (app_main.token_digest("test-other-student-token"), "student", 2, "2024020816", "周予安",
                 now + 3600, app_main.now_text()),
            ],
        )
        db.commit()
        db.close()

    def _book(self, room_id: int, start_at: str, end_at: str, headers=None) -> int:
        db = self._connect()
        db.execute("UPDATE rooms SET status = 'open', status_note = '' WHERE id = ?", (room_id,))
        db.commit()
        db.close()
        response = self.client.post(
            "/api/bookings",
            json={"user_id": 1, "room_id": room_id, "start_at": start_at, "end_at": end_at},
            headers=headers or STUDENT_HEADERS,
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["id"]

    def _room_status(self, room_id: int) -> str:
        db = self._connect()
        row = db.execute("SELECT status FROM rooms WHERE id = ?", (room_id,)).fetchone()
        db.close()
        return row["status"]

    def _booking_status(self, booking_id: int) -> str:
        db = self._connect()
        row = db.execute("SELECT status FROM bookings WHERE id = ?", (booking_id,)).fetchone()
        db.close()
        return row["status"]

    def _count(self, sql: str) -> int:
        db = self._connect()
        value = db.execute(sql).fetchone()[0]
        db.close()
        return value

    # ---- 被测场景 ----
    def test_cancel_future_booking_keeps_occupied_seat(self) -> None:
        now = datetime.now().replace(second=0, microsecond=0)
        fmt = "%Y-%m-%d %H:%M"
        b1 = self._book(1, (now + timedelta(hours=2)).strftime(fmt),
                        (now + timedelta(hours=4)).strftime(fmt))
        b2 = self._book(1, (now - timedelta(minutes=5)).strftime(fmt),
                        (now + timedelta(minutes=55)).strftime(fmt))
        self.client.patch(f"/api/bookings/{b2}/status?status=checked_in", headers=STUDENT_HEADERS)
        self.assertEqual(self._room_status(1), "occupied", "前置条件：座位应已被 b2 占用")

        violations_before = self._count("SELECT COUNT(*) FROM violations")

        r = self.client.patch(f"/api/bookings/{b1}/status?status=cancelled", headers=STUDENT_HEADERS)
        self.assertEqual(r.status_code, 200, r.text)

        self.assertEqual(self._room_status(1), "occupied", "取消未来预约不应释放正在使用的座位")
        self.assertEqual(self._booking_status(b1), "cancelled")
        self.assertEqual(self._booking_status(b2), "checked_in")
        self.assertEqual(self._count("SELECT COUNT(*) FROM violations"), violations_before)


if __name__ == "__main__":
    unittest.main()
