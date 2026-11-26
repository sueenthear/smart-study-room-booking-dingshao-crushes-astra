"""TASK-001 测试：信用分与违约规则（郑晨宇）

依据：01_需求规格说明书.md（FR-13 / BR-09 / BR-10 / AC-10 / ST-04 / FR-11 / FR-12）
      + evidence/预期确认表.md 第 1 组
代码基线：7416c19

预期来源规则：
  · 能追到 FR/BR/AC 的断言，注释中标编号；
  · 追不到需求的（等级阈值边界名称、日期展示格式），标「当前实现行为，仅作重构安全网」；
  · 不为让测试通过而修改 app/ 下生产代码。

运行：uv run python -m unittest tests.test_credit_zcy -v
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main as app_main

TMP_ROOT = Path(__file__).resolve().parent.parent / "tmp"
TMP_ROOT.mkdir(exist_ok=True)


def make_temp_dir() -> tempfile.TemporaryDirectory:
    """显式指定临时目录，规避部分 Windows 环境 TMP 不可用的问题。"""
    # ignore_cleanup_errors：Windows 下 TestClient 关闭后连接可能短暂占用 .db 文件，
    # 忽略清理阶段的 WinError 32，避免把测试成功误报成 ERROR。
    return tempfile.TemporaryDirectory(dir=str(TMP_ROOT), ignore_cleanup_errors=True)


ADMIN = ("admin", "admin123456")
STUDENT_A = ("2024010201", "123456aa")
BLACKLISTED = ("2023031108", "123456aa")


def iso(days_ago: int) -> str:
    return (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M")


def minute_offset(minutes: int) -> str:
    return (datetime.now() + timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M")


class CreditRatingUnitTests(unittest.TestCase):
    """TC-C-U01～U04：calculate_credit_rating（BR-09：基准 5.0、每次 0.4、下限 1.0）"""

    def test_c_u01_zero_violation_is_base_score(self) -> None:
        self.assertEqual(app_main.calculate_credit_rating(0), 5.0)

    def test_c_u02_one_violation_deducts_point_four(self) -> None:
        self.assertEqual(app_main.calculate_credit_rating(1), 4.6)

    def test_c_u03_twelve_violations_reach_floor(self) -> None:
        self.assertEqual(app_main.calculate_credit_rating(12), 1.0)

    def test_c_u04_thirteen_violations_stay_at_floor(self) -> None:
        self.assertEqual(app_main.calculate_credit_rating(13), 1.0)


class CreditLevelUnitTests(unittest.TestCase):
    """TC-C-U05～U09：credit_level（当前实现行为，需求未规定等级阈值名称，仅作重构安全网）"""

    def test_c_u05_full_score_is_excellent(self) -> None:
        level, label = app_main.credit_level(5.0)
        self.assertEqual((level, label), ("excellent", "信用优秀"))

    def test_c_u06_four_point_five_is_good(self) -> None:
        self.assertEqual(app_main.credit_level(4.5)[0], "good")

    def test_c_u07_four_point_zero_is_watch(self) -> None:
        self.assertEqual(app_main.credit_level(4.0)[0], "watch")

    def test_c_u08_three_point_five_is_risk(self) -> None:
        self.assertEqual(app_main.credit_level(3.5)[0], "risk")

    def test_c_u09_three_point_four_is_high_risk(self) -> None:
        self.assertEqual(app_main.credit_level(3.4)[0], "high_risk")


class ActiveViolationUnitTests(unittest.TestCase):
    """TC-C-U10～U12：count_active_violations（BR-10：满 90 天不再计入）"""

    def setUp(self) -> None:
        self.tmp = make_temp_dir()
        self.db_path = Path(self.tmp.name) / "unit.db"
        self.db = sqlite3.connect(self.db_path)
        self.db.row_factory = sqlite3.Row
        self.db.execute(
            "CREATE TABLE violations (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "user_id INTEGER, reason TEXT, source TEXT, created_at TEXT)"
        )
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()

    def _insert(self, days_ago: int) -> None:
        self.db.execute(
            "INSERT INTO violations(user_id, reason, source, created_at) VALUES (1, ?, 'system', ?)",
            ("测试违约", iso(days_ago)),
        )
        self.db.commit()

    def test_c_u10_89_day_record_counts(self) -> None:
        self._insert(89)
        self.assertEqual(app_main.count_active_violations(self.db, 1), 1)

    def test_c_u11_90_day_record_counts(self) -> None:
        # BR-10「满 90 天不再计入」按 >90 天边界：第 90 天仍计入
        self._insert(90)
        self.assertEqual(app_main.count_active_violations(self.db, 1), 1)

    def test_c_u12_91_day_record_does_not_count(self) -> None:
        self._insert(91)
        self.assertEqual(app_main.count_active_violations(self.db, 1), 0)


class SyncRatingUnitTests(unittest.TestCase):
    """TC-C-U13～U14：sync_user_rating（FR-13：信用分按有效违约数重算）"""

    def setUp(self) -> None:
        self.tmp = make_temp_dir()
        self.db_path = Path(self.tmp.name) / "sync.db"
        self.db = sqlite3.connect(self.db_path)
        self.db.row_factory = sqlite3.Row
        self.db.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, rating REAL NOT NULL DEFAULT 5.0)"
        )
        self.db.execute(
            "CREATE TABLE violations (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, reason TEXT, "
            "source TEXT, created_at TEXT)"
        )
        self.db.execute("INSERT INTO users(id, rating) VALUES (1, 5.0)")
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()

    def test_c_u13_syncs_rating_from_active_violations(self) -> None:
        self.db.execute(
            "INSERT INTO violations(user_id, reason, source, created_at) VALUES (1, ?, 'system', ?)",
            ("测试违约", iso(1)),
        )
        self.db.commit()
        score = app_main.sync_user_rating(self.db, 1)
        self.assertEqual(score, 4.6)
        stored = self.db.execute("SELECT rating FROM users WHERE id = 1").fetchone()["rating"]
        self.assertEqual(stored, 4.6)

    def test_c_u14_missing_user_returns_none(self) -> None:
        self.assertIsNone(app_main.sync_user_rating(self.db, 999))


class BackfillUnitTests(unittest.TestCase):
    """TC-C-U15～U16：backfill_violation_history（历史违约补录，不重复）"""

    def setUp(self) -> None:
        self.tmp = make_temp_dir()
        self.db_path = Path(self.tmp.name) / "backfill.db"
        self.db = sqlite3.connect(self.db_path)
        self.db.row_factory = sqlite3.Row
        self.db.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, violations INTEGER DEFAULT 0, created_at TEXT)"
        )
        self.db.execute(
            "CREATE TABLE violations (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, reason TEXT, "
            "source TEXT, created_at TEXT)"
        )
        self.db.execute("INSERT INTO users(id, violations, created_at) VALUES (1, 3, ?)", (iso(100),))
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()

    def test_c_u15_backfills_missing_records(self) -> None:
        app_main.backfill_violation_history(self.db)
        count = self.db.execute("SELECT COUNT(*) FROM violations WHERE user_id = 1").fetchone()[0]
        self.assertEqual(count, 3)

    def test_c_u16_backfill_is_idempotent(self) -> None:
        app_main.backfill_violation_history(self.db)
        app_main.backfill_violation_history(self.db)
        count = self.db.execute("SELECT COUNT(*) FROM violations WHERE user_id = 1").fetchone()[0]
        self.assertEqual(count, 3)


class CutoffTextUnitTests(unittest.TestCase):
    """TC-C-U17～U18：credit_cutoff_text（BR-10：90 天截止）"""

    def test_c_u17_format_is_minute_precision(self) -> None:
        # 当前实现行为，需求未规定展示格式，仅作重构安全网
        text = app_main.credit_cutoff_text()
        parsed = datetime.strptime(text, "%Y-%m-%d %H:%M")
        self.assertIsInstance(parsed, datetime)

    def test_c_u18_cutoff_is_ninety_days_ago(self) -> None:
        parsed = datetime.strptime(app_main.credit_cutoff_text(), "%Y-%m-%d %H:%M")
        self.assertAlmostEqual((datetime.now() - parsed).total_seconds(), 90 * 86400, delta=120)


class RoundingUnitTests(unittest.TestCase):
    """TC-C-U19～U20：calculate_credit_rating 舍入（当前实现行为，仅作重构安全网）"""

    def test_c_u19_two_violations_is_four_point_two(self) -> None:
        self.assertEqual(app_main.calculate_credit_rating(2), 4.2)

    def test_c_u20_three_violations_is_three_point_eight(self) -> None:
        self.assertEqual(app_main.calculate_credit_rating(3), 3.8)


class CreditApiTests(unittest.TestCase):
    """TC-C-I01～I10：信用规则集成（FR-13 / BR-09 / BR-10 / AC-10 / FR-11 / FR-12）"""

    def setUp(self) -> None:
        self.tmp = make_temp_dir()
        self.db_path = Path(self.tmp.name) / "api.db"
        self.db_patch = patch.object(app_main, "DB_PATH", self.db_path)
        self.db_patch.start()
        app_main.init_db()
        self.client = TestClient(app_main.app, raise_server_exceptions=False)

    def tearDown(self) -> None:
        self.client.close()
        self.db_patch.stop()
        self.tmp.cleanup()

    def _db(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def _login(self, account: str, password: str, role: str = "student") -> dict[str, str]:
        resp = self.client.post(
            "/api/auth/login", json={"account": account, "password": password, "role": role}
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        return {"Authorization": f"Bearer {resp.json()['token']}"}

    def _credit(self, user_id: int, headers: dict[str, str]) -> float:
        resp = self.client.get(f"/api/users/{user_id}/credit-profile", headers=headers)
        self.assertEqual(resp.status_code, 200, resp.text)
        # 接口在 credit-profile 返回的字段名是 score（见 main.py 实现），不是 rating
        return float(resp.json()["score"])

    def _user_id(self, account: str) -> int:
        db = self._db()
        row = db.execute("SELECT id FROM users WHERE student_no = ?", (account,)).fetchone()
        db.close()
        return int(row["id"])

    def _insert_violation(self, user_id: int, when: str) -> None:
        db = self._db()
        db.execute(
            "INSERT INTO violations(user_id, reason, source, created_at) VALUES (?, ?, 'system', ?)",
            (user_id, "测试违约", when),
        )
        db.commit()
        db.close()

    # ---- TC-C-I01 违约→扣分联动（BR-09、AC-05） ----
    def test_c_i01_violation_deducts_credit(self) -> None:
        uid = self._user_id(STUDENT_A[0])
        self._insert_violation(uid, iso(1))
        self.assertEqual(self._credit(uid, self._login(*STUDENT_A)), 4.6)

    # ---- TC-C-I02 扣分下限（BR-09） ----
    def test_c_i02_credit_floor_is_one(self) -> None:
        uid = self._user_id(STUDENT_A[0])
        for _ in range(12):
            self._insert_violation(uid, iso(1))
        self.assertEqual(self._credit(uid, self._login(*STUDENT_A)), 1.0)

    # ---- TC-C-I03 迟到边界（BR-07，Q-05 已关闭；本用例验 15 分钟整不违约） ----
    def test_c_i03_late_15_minutes_does_not_create_violation(self) -> None:
        uid = self._user_id(STUDENT_A[0])
        headers = self._login(*STUDENT_A)
        db = self._db()
        db.execute(
            "INSERT INTO bookings(user_id, room_id, start_at, end_at, status, created_at) "
            "VALUES (?, 1, ?, ?, 'booked', ?)",
            (uid, minute_offset(-15), minute_offset(60), iso(0)),
        )
        db.commit()
        bid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.close()
        before = self._credit(uid, headers)
        resp = self.client.patch(f"/api/bookings/{bid}/status?status=checked_in", headers=headers)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(self._credit(uid, headers), before)

    # ---- TC-C-I04 90 天恢复（BR-10、AC-10） ----
    def test_c_i04_expired_violation_recovers_credit(self) -> None:
        uid = self._user_id(STUDENT_A[0])
        self._insert_violation(uid, iso(91))
        self.assertEqual(self._credit(uid, self._login(*STUDENT_A)), 5.0)

    # ---- TC-C-I05 信用档位读取（FR-13，实现字段） ----
    def test_c_i05_credit_profile_exposes_level(self) -> None:
        uid = self._user_id(STUDENT_A[0])
        resp = self.client.get(f"/api/users/{uid}/credit-profile", headers=self._login(*STUDENT_A))
        self.assertIn("level", resp.json())
        self.assertIn("level_label", resp.json())

    # ---- TC-C-I06 管理员手动登记违约后信用分同步（FR-13） ----
    def test_c_i06_admin_manual_violation_syncs_rating(self) -> None:
        uid = self._user_id(STUDENT_A[0])
        resp = self.client.post(
            "/api/violations",
            json={"user_id": uid, "reason": "管理员登记"},
            headers=self._login(*ADMIN, role="admin"),
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(self._credit(uid, self._login(*STUDENT_A)), 4.6)

    # ---- TC-C-I07 黑名单到期自动解封（FR-14） ----
    def test_c_i07_expired_blacklist_released(self) -> None:
        db = self._db()
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        db.execute(
            "INSERT INTO users(student_no, name, phone, password, blacklisted, blacklisted_until, created_at) "
            "VALUES ('2099000099', '到期学生', '', '123456aa', 1, ?, ?)",
            (yesterday, iso(10)),
        )
        db.commit()
        db.close()
        resp = self.client.post(
            "/api/auth/login",
            json={"account": "2099000099", "password": "123456aa", "role": "student"},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertFalse(resp.json()["blacklisted"])

    # ---- TC-C-I08 受限账号不可创建预约（BR-11；决定改 403、现实现 400） ----
    @unittest.expectedFailure
    def test_c_i08_blacklisted_booking_returns_403(self) -> None:
        resp = self.client.post(
            "/api/bookings",
            json={
                "user_id": 0,
                "room_id": 1,
                "start_at": minute_offset(120),
                "end_at": minute_offset(180),
            },
            headers=self._login(*BLACKLISTED),
        )
        self.assertEqual(resp.status_code, 403, resp.text)

    # ---- TC-C-I09 登录时信用分同步（FR-13） ----
    def test_c_i09_login_syncs_rating(self) -> None:
        uid = self._user_id(STUDENT_A[0])
        self._insert_violation(uid, iso(1))
        db = self._db()
        db.execute("UPDATE users SET rating = 5.0 WHERE id = ?", (uid,))
        db.commit()
        db.close()
        self._login(*STUDENT_A)
        db = self._db()
        score = db.execute("SELECT rating FROM users WHERE id = ?", (uid,)).fetchone()["rating"]
        db.close()
        self.assertEqual(score, 4.6)

    # ---- TC-C-I10 违约记录按用户过滤（FR-12） ----
    def test_c_i10_violation_query_scoped_to_self(self) -> None:
        headers = self._login(*STUDENT_A)
        resp = self.client.get("/api/violations", headers=headers)
        self.assertEqual(resp.status_code, 200, resp.text)
        for item in resp.json():
            self.assertEqual(item["user_id"], self._user_id(STUDENT_A[0]))


if __name__ == "__main__":
    unittest.main()
