from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main as app_main


ADMIN_HEADERS = {"Authorization": "Bearer test-task-admin-token"}
TRACKED_TABLES = {
    "auth_sessions",
    "bookings",
    "classrooms",
    "complaints",
    "rooms",
    "users",
    "violations",
}


class IsolatedDatabaseTestCase(unittest.TestCase):
    """Run every test against a fresh SQLite database without touching demo data."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "task-004.db"
        self.db_patch = patch.object(app_main, "DB_PATH", self.db_path)
        self.db_patch.start()
        app_main.init_db()

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def connect(self) -> sqlite3.Connection:
        return app_main.connect_db()


class InfrastructureUnitTests(IsolatedDatabaseTestCase):
    """TASK-004 unit cases and supporting infrastructure assertions."""

    # Unit 1: schema completeness.
    def test_unit_01_init_db_creates_complete_schema(self) -> None:
        with closing(self.connect()) as db:
            tables = {
                row[0]
                for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            classroom_foreign_keys = db.execute(
                "PRAGMA foreign_key_list(rooms)"
            ).fetchall()

        self.assertTrue(TRACKED_TABLES.issubset(tables), tables)
        self.assertTrue(
            any(
                row["table"] == "classrooms"
                and row["from"] == "classroom_id"
                and row["to"] == "id"
                for row in classroom_foreign_keys
            ),
            classroom_foreign_keys,
        )

    # Unit 2: required demonstration data.
    def test_unit_02_init_db_seeds_demo_data(self) -> None:
        with closing(self.connect()) as db:
            classroom_count = db.execute("SELECT COUNT(*) FROM classrooms").fetchone()[0]
            room_count = db.execute("SELECT COUNT(*) FROM rooms").fetchone()[0]
            user_count = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            booking_count = db.execute("SELECT COUNT(*) FROM bookings").fetchone()[0]
            complaint_count = db.execute("SELECT COUNT(*) FROM complaints").fetchone()[0]
            violation_count = db.execute("SELECT COUNT(*) FROM violations").fetchone()[0]

        self.assertEqual(classroom_count, 4)
        self.assertEqual(room_count, 12)
        self.assertEqual(user_count, 5)
        self.assertGreaterEqual(booking_count, 1)
        self.assertGreaterEqual(complaint_count, 1)
        self.assertGreaterEqual(violation_count, 1)

    # Unit 3: repeated initialization is idempotent.
    def test_unit_03_init_db_is_idempotent(self) -> None:
        def snapshot() -> tuple[int, ...]:
            with closing(self.connect()) as db:
                return tuple(
                    db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    for table in (
                        "classrooms",
                        "rooms",
                        "users",
                        "bookings",
                        "complaints",
                        "violations",
                    )
                )

        before = snapshot()
        app_main.init_db()
        app_main.init_db()
        self.assertEqual(snapshot(), before)

    # Unit 3b: initialization enables SQLite WAL for concurrent readers.
    def test_unit_03b_init_db_enables_wal_mode(self) -> None:
        with closing(self.connect()) as db:
            journal_mode = db.execute("PRAGMA journal_mode").fetchone()[0]

        self.assertEqual(journal_mode.lower(), "wal")

    # Unit 4: connection enables foreign-key enforcement.
    def test_unit_04_connect_db_enables_foreign_keys(self) -> None:
        with closing(self.connect()) as db:
            self.assertEqual(db.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute(
                    "INSERT INTO rooms(name, classroom_id, floor, capacity, status, features, created_at) "
                    "VALUES ('invalid-room', 999999, '一层', 1, 'open', '', ?)",
                    (app_main.now_text(),),
                )
            db.rollback()

    # Unit 5: connection configures the promised wait period.
    def test_unit_05_connect_db_sets_busy_timeout(self) -> None:
        with closing(self.connect()) as db:
            self.assertEqual(db.execute("PRAGMA busy_timeout").fetchone()[0], 30_000)

    # Unit 6: credit formula and floor.
    def test_unit_06_calculate_credit_rating_formula(self) -> None:
        self.assertEqual(app_main.calculate_credit_rating(0), 5.0)
        self.assertEqual(app_main.calculate_credit_rating(1), 4.6)
        self.assertEqual(app_main.calculate_credit_rating(5), 3.0)
        self.assertEqual(app_main.calculate_credit_rating(10), 1.0)
        self.assertEqual(app_main.calculate_credit_rating(100), 1.0)

    # Unit 7: independent cross-check of the same credit rule.
    def test_unit_07_calculate_credit_rating_cross_check(self) -> None:
        for violation_count in range(11):
            self.assertAlmostEqual(
                app_main.calculate_credit_rating(violation_count),
                max(
                    1.0,
                    round(
                        app_main.RATING_BASE
                        - violation_count * app_main.RATING_PENALTY_PER_VIOLATION,
                        2,
                    ),
                ),
            )

    # Unit 8: exact label boundaries.
    def test_unit_08_credit_level_boundaries(self) -> None:
        cases = [
            (5.0, ("excellent", "信用优秀")),
            (4.99, ("good", "信用良好")),
            (4.5, ("good", "信用良好")),
            (4.49, ("watch", "需要保持")),
            (4.0, ("watch", "需要保持")),
            (3.99, ("risk", "信用偏低")),
            (3.5, ("risk", "信用偏低")),
            (3.49, ("high_risk", "高风险")),
            (1.0, ("high_risk", "高风险")),
        ]
        for score, expected in cases:
            with self.subTest(score=score):
                self.assertEqual(app_main.credit_level(score), expected)

    # Unit 9: independent cross-check across every label.
    def test_unit_09_credit_level_cross_check(self) -> None:
        labels = {
            app_main.credit_level(score)[0]
            for score in (5.0, 4.8, 4.2, 3.7, 3.0)
        }
        self.assertEqual(
            labels,
            {"excellent", "good", "watch", "risk", "high_risk"},
        )

    # Unit 10: capacity aggregation.
    def test_unit_10_sync_classroom_capacities_aggregates_rooms(self) -> None:
        with closing(self.connect()) as db:
            before = db.execute("SELECT capacity FROM classrooms WHERE id = 1").fetchone()[0]
            db.execute(
                "INSERT INTO rooms(name, classroom_id, floor, capacity, status, features, created_at) "
                "VALUES ('TASK-004-A', 1, '一层', 1, 'open', '', ?)",
                (app_main.now_text(),),
            )
            app_main.sync_classroom_capacities(db)
            after = db.execute("SELECT capacity FROM classrooms WHERE id = 1").fetchone()[0]

        self.assertEqual(after, before + 1)

    # Unit 11: all-maintenance classroom is closed for display.
    def test_unit_11_sync_classroom_capacities_all_maintenance(self) -> None:
        with closing(self.connect()) as db:
            db.execute("UPDATE rooms SET status = 'maintenance' WHERE classroom_id = 1")
            db.execute(
                "UPDATE rooms SET status = 'maintenance' WHERE classroom_id = 1 AND status = 'occupied'"
            )
            app_main.sync_classroom_capacities(db)
            status = db.execute("SELECT status FROM classrooms WHERE id = 1").fetchone()[0]

        self.assertEqual(status, "maintenance")

    # Unit 12: a non-maintenance room reopens the classroom.
    def test_unit_12_sync_classroom_capacities_partial_maintenance(self) -> None:
        with closing(self.connect()) as db:
            db.execute("UPDATE rooms SET status = 'maintenance' WHERE classroom_id = 1")
            db.execute(
                "UPDATE rooms SET status = 'maintenance' WHERE classroom_id = 1 AND status = 'occupied'"
            )
            db.execute("UPDATE rooms SET status = 'open' WHERE id = 1")
            app_main.sync_classroom_capacities(db)
            status = db.execute("SELECT status FROM classrooms WHERE id = 1").fetchone()[0]

        self.assertEqual(status, "open")

    # Unit 13: account snapshot preserves the fields consumers need.
    def test_unit_13_account_snapshot_has_complete_status_fields(self) -> None:
        snapshot = app_main.account_snapshot(
            {
                "id": 1,
                "name": "测试学生",
                "student_no": "2026000001",
                "phone": "13812345678",
                "violations": 0,
                "blacklisted": 0,
                "blacklisted_until": None,
                "blacklisted_at": None,
                "blacklist_reason": None,
                "rating": 4.6,
                "created_at": "2026-01-01 09:00",
            }
        )
        required = {
            "id",
            "name",
            "student_no",
            "phone",
            "rating",
            "blacklisted",
            "is_blacklisted",
            "blacklisted_until",
            "blacklisted_at",
            "blacklist_reason",
            "unban_date",
            "days_remaining",
            "status",
            "status_label",
            "status_message",
            "credit_level",
            "credit_level_label",
        }
        self.assertTrue(required.issubset(snapshot), snapshot.keys())
        self.assertEqual(snapshot["status"], "active")
        self.assertEqual(snapshot["credit_level"], "good")

    # Unit 14: account snapshot never exposes passwords.
    def test_unit_14_account_snapshot_removes_password(self) -> None:
        snapshot = app_main.account_snapshot(
            {
                "id": 2,
                "name": "受限学生",
                "student_no": "2026000002",
                "phone": "13912345678",
                "password": "must-not-leak",
                "violations": 2,
                "blacklisted": 1,
                "blacklisted_until": "2030-01-10 23:59",
                "blacklisted_at": "2030-01-03 09:00",
                "blacklist_reason": "测试限制",
                "rating": 4.2,
                "created_at": "2026-01-01 09:00",
            }
        )
        self.assertNotIn("password", snapshot)
        self.assertEqual(snapshot["status"], "blacklisted")
        self.assertEqual(snapshot["unban_date"], "2030-01-10")
        self.assertGreaterEqual(snapshot["days_remaining"], 1)

    # Unit 15: empty query result.
    def test_unit_15_rows_to_dict_empty_result(self) -> None:
        with closing(self.connect()) as db:
            rows = db.execute("SELECT * FROM users WHERE 0").fetchall()
        self.assertEqual(app_main.rows_to_dict(rows), [])

    # Unit 16: single query result.
    def test_unit_16_rows_to_dict_single_result(self) -> None:
        with closing(self.connect()) as db:
            rows = db.execute(
                "SELECT id, name FROM users WHERE id = 1"
            ).fetchall()
        result = app_main.rows_to_dict(rows)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], 1)
        self.assertIn("name", result[0])

    # Unit 17: default blacklist date crosses a month boundary.
    def test_unit_17_default_blacklist_until_across_month(self) -> None:
        now = datetime(2030, 1, 28, 10, 30)
        with patch.object(app_main, "datetime", wraps=datetime) as datetime_mock:
            datetime_mock.now.return_value = now
            self.assertEqual(app_main.default_blacklist_until(), "2030-02-04 23:59")

    # Unit 18: default blacklist date crosses a year boundary.
    def test_unit_18_default_blacklist_until_across_year(self) -> None:
        now = datetime(2030, 12, 29, 8, 15)
        with patch.object(app_main, "datetime", wraps=datetime) as datetime_mock:
            datetime_mock.now.return_value = now
            self.assertEqual(app_main.default_blacklist_until(), "2031-01-05 23:59")
        self.assertEqual(
            (now + timedelta(days=7)).strftime("%Y-%m-%d 23:59"),
            "2031-01-05 23:59",
        )

    # Unit 19: cutoff and violation counting use the same time boundary.
    def test_unit_19_credit_cutoff_matches_active_violation_count(self) -> None:
        cutoff = "2029-12-31 12:00"
        with patch.object(app_main, "credit_cutoff_text", return_value=cutoff):
            with closing(self.connect()) as db:
                db.execute(
                    "INSERT INTO violations(user_id, reason, source, created_at) "
                    "VALUES (1, 'expired', 'system', '2029-12-30 23:59')"
                )
                db.execute(
                    "INSERT INTO violations(user_id, reason, source, created_at) "
                    "VALUES (1, 'active-at-boundary', 'system', ?)",
                    (cutoff,),
                )
                db.execute(
                    "INSERT INTO violations(user_id, reason, source, created_at) "
                    "VALUES (1, 'active-after-boundary', 'system', '2029-12-31 12:01')"
                )
                count = app_main.count_active_violations(db, 1)

        self.assertEqual(count, 2)

    # Unit 20: independent cutoff check.
    def test_unit_20_credit_cutoff_cross_check(self) -> None:
        fixed_now = datetime(2030, 1, 1, 0, 0)
        with patch.object(app_main, "datetime", wraps=datetime) as datetime_mock:
            datetime_mock.now.return_value = fixed_now
            cutoff = app_main.credit_cutoff_text()
        self.assertEqual(cutoff, "2029-10-03 00:00")
        self.assertEqual(
            (fixed_now - timedelta(days=app_main.CREDIT_RECOVERY_DAYS)).strftime(
                "%Y-%m-%d %H:%M"
            ),
            cutoff,
        )


class IntegrationTests(IsolatedDatabaseTestCase):
    """TASK-004 integration cases through the real FastAPI routes."""

    def setUp(self) -> None:
        super().setUp()
        self.client = TestClient(app_main.app)
        with closing(self.connect()) as db:
            db.execute(
                "INSERT INTO auth_sessions(token_hash, role, user_id, account, name, expires_at, created_at) "
                "VALUES (?, 'admin', NULL, 'admin', 'test-admin', ?, ?)",
                (
                    app_main.token_digest("test-task-admin-token"),
                    int(app_main.time()) + 3600,
                    app_main.now_text(),
                ),
            )
            db.commit()

    def tearDown(self) -> None:
        self.client.close()
        super().tearDown()

    def classroom_payload(self, name: str = "测试教室") -> dict[str, object]:
        return {
            "name": name,
            "building": "主楼",
            "floor": "五层",
            "capacity": 99,
            "status": "open",
            "features": "白板",
        }

    # Integration 1 / FR-10.
    def test_integration_01_create_classroom(self) -> None:
        response = self.client.post(
            "/api/classrooms",
            json=self.classroom_payload("TASK-004 新教室"),
            headers=ADMIN_HEADERS,
        )
        self.assertEqual(response.status_code, 200, response.text)
        classroom_id = response.json()["id"]
        with closing(self.connect()) as db:
            row = db.execute(
                "SELECT name, floor, capacity, status FROM classrooms WHERE id = ?",
                (classroom_id,),
            ).fetchone()
        self.assertEqual((row["name"], row["floor"]), ("TASK-004 新教室", "五层"))
        self.assertEqual((row["capacity"], row["status"]), (0, "open"))

    # Integration 2 / FR-10.
    def test_integration_02_update_classroom(self) -> None:
        response = self.client.patch(
            "/api/classrooms/2",
            json=self.classroom_payload("TASK-004 已更新"),
            headers=ADMIN_HEADERS,
        )
        self.assertEqual(response.status_code, 200, response.text)
        with closing(self.connect()) as db:
            row = db.execute(
                "SELECT name, building, floor, features FROM classrooms WHERE id = 2"
            ).fetchone()
        self.assertEqual(row["name"], "TASK-004 已更新")
        self.assertEqual(row["features"], "白板")

    # Integration 3 / FR-10.
    def test_integration_03_delete_classroom(self) -> None:
        response = self.client.post(
            "/api/classrooms",
            json=self.classroom_payload("TASK-004 待删除"),
            headers=ADMIN_HEADERS,
        )
        self.assertEqual(response.status_code, 200, response.text)
        classroom_id = response.json()["id"]
        response = self.client.delete(
            f"/api/classrooms/{classroom_id}", headers=ADMIN_HEADERS
        )
        self.assertEqual(response.status_code, 200, response.text)
        with closing(self.connect()) as db:
            count = db.execute(
                "SELECT COUNT(*) FROM classrooms WHERE id = ?", (classroom_id,)
            ).fetchone()[0]
        self.assertEqual(count, 0)

    # Integration 4 / FR-11.
    def test_integration_04_create_student(self) -> None:
        response = self.client.post(
            "/api/users",
            json={
                "name": "任务测试学生",
                "student_no": "2099000001",
                "phone": "13800000001",
                "password": "taskpass1",
            },
            headers=ADMIN_HEADERS,
        )
        self.assertEqual(response.status_code, 200, response.text)
        user_id = response.json()["id"]
        with closing(self.connect()) as db:
            row = db.execute(
                "SELECT name, student_no, phone, password FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        self.assertEqual(
            (row["name"], row["student_no"], row["phone"]),
            ("任务测试学生", "2099000001", "13800000001"),
        )
        self.assertEqual(row["password"], "taskpass1")

    # Integration 5 / FR-11.
    def test_integration_05_update_student(self) -> None:
        response = self.client.patch(
            "/api/users/1",
            json={
                "name": "任务更新学生",
                "student_no": "2024010201",
                "phone": "13800000002",
            },
            headers=ADMIN_HEADERS,
        )
        self.assertEqual(response.status_code, 200, response.text)
        with closing(self.connect()) as db:
            row = db.execute(
                "SELECT name, phone FROM users WHERE id = 1"
            ).fetchone()
        self.assertEqual((row["name"], row["phone"]), ("任务更新学生", "13800000002"))

    # Integration 6 / FR-11.
    def test_integration_06_delete_student(self) -> None:
        response = self.client.post(
            "/api/users",
            json={
                "name": "任务删除学生",
                "student_no": "2099000002",
                "phone": "13800000003",
            },
            headers=ADMIN_HEADERS,
        )
        self.assertEqual(response.status_code, 200, response.text)
        user_id = response.json()["id"]
        response = self.client.delete(
            f"/api/users/{user_id}", headers=ADMIN_HEADERS
        )
        self.assertEqual(response.status_code, 200, response.text)
        with closing(self.connect()) as db:
            count = db.execute(
                "SELECT COUNT(*) FROM users WHERE id = ?", (user_id,)
            ).fetchone()[0]
        self.assertEqual(count, 0)

    # Integration 7 / FR-11.
    def test_integration_07_import_students_from_csv(self) -> None:
        csv_content = (
            "name,student_no,phone,password\r\n"
            "导入甲,2099000011,13800000011,taskpass1\r\n"
            "导入乙,2099000012,13800000012,\r\n"
        )
        response = self.client.post(
            "/api/users/import",
            files={"file": ("students.csv", csv_content.encode("utf-8-sig"), "text/csv")},
            headers=ADMIN_HEADERS,
        )
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result["created"], 2)
        self.assertEqual(result["skipped"], [])
        with closing(self.connect()) as db:
            rows = {
                row["student_no"]: row["password"]
                for row in db.execute(
                    "SELECT student_no, password FROM users WHERE student_no LIKE '209900001%'"
                ).fetchall()
            }
        self.assertEqual(rows["2099000011"], "taskpass1")
        self.assertEqual(rows["2099000012"], "123456aa")

    # Integration 8 / FR-15.
    def test_integration_08_overview(self) -> None:
        with closing(self.connect()) as db:
            expected = {
                "room_total": db.execute("SELECT COUNT(*) FROM rooms").fetchone()[0],
                "booked": db.execute(
                    "SELECT COUNT(*) FROM bookings WHERE status = 'booked'"
                ).fetchone()[0],
                "pending_complaints": db.execute(
                    "SELECT COUNT(*) FROM complaints WHERE status != '已完成'"
                ).fetchone()[0],
            }
        response = self.client.get("/api/overview", headers=ADMIN_HEADERS)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        for key, value in expected.items():
            self.assertEqual(body[key], value)
        required = {
            "room_total",
            "seat_total",
            "open_rooms",
            "occupied",
            "maintenance_rooms",
            "booked",
            "active_users",
            "violation_count",
            "pending_complaints",
            "updated_at",
        }
        self.assertTrue(required.issubset(body))

    # Integration 9 / FR-15.
    def test_integration_09_analytics_four_stat_groups(self) -> None:
        response = self.client.get("/api/analytics", headers=ADMIN_HEADERS)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(len(body["daily"]), 7)
        self.assertTrue(body["zones"])
        self.assertTrue(body["popular_seats"])
        self.assertIsInstance(body["no_show_rate"], float)
        self.assertEqual(body["refresh_seconds"], 10)
        for item in body["daily"]:
            self.assertEqual(set(item), {"label", "value"})
        for item in body["zones"]:
            self.assertEqual(set(item), {"zone", "value"})
        for item in body["popular_seats"]:
            self.assertTrue(
                {
                    "id",
                    "name",
                    "classroom_name",
                    "booking_count",
                    "completed_count",
                    "violation_count",
                }.issubset(item)
            )

    # Integration 10: homepage.
    def test_integration_10_homepage_returns_html(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertTrue(response.text.lstrip().lower().startswith("<!doctype html"))
        self.assertIn("<html", response.text.lower())


if __name__ == "__main__":
    unittest.main()
