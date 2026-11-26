"""TASK-003 单元测试：权限、投诉与黑名单（TC-U01～TC-U20）

依据：docs/01_需求规格说明书.md（2026-11-01 提交版）
      + docs/架构确认与决策记录.md（2026-11-26 业务侧决定）
代码基线：main 7416c19

预期来源规则（重要）：
  · 能追到 BR/FR 的断言，注释中标编号；
  · 追不到需求的（信用等级阈值、日期格式），标「当前实现行为，需求未规定」，
    这类断言只用于固定行为、作重构安全网，不得当作业务规则引用；
  · 不为让测试通过而修改 app/ 下生产代码。

运行：uv run python -m unittest tests.test_auth_permission -v
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import main as app_main


class CreditRatingTests(unittest.TestCase):
    """TC-U01～U04：calculate_credit_rating（依据 BR-09：基准 5.0、每次 0.4、下限 1.0）"""

    def test_tc_u01_zero_violation_is_base_score(self) -> None:
        self.assertEqual(app_main.calculate_credit_rating(0), 5.0)

    def test_tc_u02_one_violation_deducts_point_four(self) -> None:
        # BR-09：每次有效违约扣 0.4
        self.assertEqual(app_main.calculate_credit_rating(1), 4.6)

    def test_tc_u03_five_violations(self) -> None:
        self.assertEqual(app_main.calculate_credit_rating(5), 3.0)

    def test_tc_u04_never_below_floor(self) -> None:
        # BR-09：最低 1.0 分
        self.assertEqual(app_main.calculate_credit_rating(12), 1.0)
        self.assertEqual(app_main.calculate_credit_rating(100), 1.0)


class CreditLevelTests(unittest.TestCase):
    """TC-U05～U08：credit_level（当前实现行为，需求未规定等级阈值，详见说明文档）"""

    def test_tc_u05_full_score_is_excellent(self) -> None:
        level, label = app_main.credit_level(5.0)
        self.assertEqual(level, "excellent")
        self.assertEqual(label, "信用优秀")

    def test_tc_u06_four_point_six_is_good(self) -> None:
        self.assertEqual(app_main.credit_level(4.6)[0], "good")

    def test_tc_u07_four_point_two_is_watch(self) -> None:
        self.assertEqual(app_main.credit_level(4.2)[0], "watch")

    def test_tc_u08_below_three_point_five_is_high_risk(self) -> None:
        self.assertEqual(app_main.credit_level(3.4)[0], "high_risk")


class CreditCutoffTests(unittest.TestCase):
    """TC-U09～U10：credit_cutoff_text（依据 BR-10：违约记录满 90 天后不计入）"""

    def test_tc_u09_format_is_minute_precision(self) -> None:
        # 格式为当前实现行为，需求未规定展示格式
        text = app_main.credit_cutoff_text()
        parsed = datetime.strptime(text, "%Y-%m-%d %H:%M")
        self.assertIsInstance(parsed, datetime)

    def test_tc_u10_cutoff_is_ninety_days_ago(self) -> None:
        parsed = datetime.strptime(app_main.credit_cutoff_text(), "%Y-%m-%d %H:%M")
        delta_seconds = (datetime.now() - parsed).total_seconds()
        self.assertAlmostEqual(delta_seconds, 90 * 86400, delta=120)


class NormalizeBlacklistUntilTests(unittest.TestCase):
    """TC-U11～U14：normalize_blacklist_until（依据 BR-11 / BR-21）"""

    def test_tc_u11_not_blacklisted_returns_none(self) -> None:
        self.assertIsNone(app_main.normalize_blacklist_until(None, False))
        self.assertIsNone(app_main.normalize_blacklist_until("2026-12-01", False))

    def test_tc_u12_date_only_fills_end_of_day(self) -> None:
        self.assertEqual(
            app_main.normalize_blacklist_until("2026-12-01", True), "2026-12-01 23:59"
        )

    def test_tc_u13_datetime_keeps_minute(self) -> None:
        self.assertEqual(
            app_main.normalize_blacklist_until("2026-12-01 18:30", True),
            "2026-12-01 18:30",
        )

    def test_tc_u14_invalid_format_raises_400(self) -> None:
        # 非法格式必须被拒，不能静默写入脏数据
        with self.assertRaises(HTTPException) as ctx:
            app_main.normalize_blacklist_until("2026/12/01", True)
        self.assertEqual(ctx.exception.status_code, 400)

    @unittest.expectedFailure
    def test_tc_u14b_empty_value_under_br21_should_be_rejected(self) -> None:
        """BR-21 要求"强制填写解封日期、不设默认值"。

        写法说明（2026-11-26 更正）：必须**直接断言期望行为**，不能用
        "先断言当前行为成立、再手动 raise" 的写法——那样 BR-21 落地时异常会先
        在第一行 assertEqual 爆掉，仍被 expectedFailure 吞掉，永远不会翻红。

        当前：空值返回默认 7 天后，不抛异常 → assertRaises 失败 → 预期失败（x）。
        BR-21 落地后：抛 HTTPException(400) → assertRaises 通过 → 变成
        「unexpected success」，套件报红，提示移除本标记。
        接口层对照见 TC-I11。
        """
        with self.assertRaises(HTTPException) as ctx:
            app_main.normalize_blacklist_until("", True)
        self.assertEqual(ctx.exception.status_code, 400)


class AccountSnapshotTests(unittest.TestCase):
    """TC-U15～U16：account_snapshot（依据 FR-14 黑名单通知、Q-P03 密码不回传）"""

    @staticmethod
    def _row(**overrides) -> dict:
        base = {
            "id": 1,
            "name": "林知夏",
            "student_no": "2024010201",
            "phone": "158****9033",
            "password": "123456aa",
            "violations": 0,
            "rating": 5.0,
            "blacklisted": 0,
            "blacklisted_until": None,
            "blacklisted_at": None,
            "blacklist_reason": "",
        }
        base.update(overrides)
        return base

    def test_tc_u15_normal_account(self) -> None:
        snapshot = app_main.account_snapshot(self._row())
        self.assertFalse(snapshot["blacklisted"])
        self.assertEqual(snapshot["status"], "active")
        self.assertIsNone(snapshot["days_remaining"])
        # Q-P03：任何接口不回传密码
        self.assertNotIn("password", snapshot)

    def test_tc_u16_blacklisted_account(self) -> None:
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d 23:59")
        with self.subTest("受限未到期"):
            snapshot = app_main.account_snapshot(
                self._row(blacklisted=1, blacklisted_until=tomorrow, blacklist_reason="多次违约")
            )
            self.assertTrue(snapshot["blacklisted"])
            self.assertEqual(snapshot["status"], "blacklisted")
            self.assertGreaterEqual(snapshot["days_remaining"], 1)
            self.assertIn("剩余", snapshot["status_message"])

        with self.subTest("受限已过期但尚未被释放"):
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d 23:59")
            snapshot = app_main.account_snapshot(
                self._row(blacklisted=1, blacklisted_until=yesterday)
            )
            # 已过期时 days_remaining 归零，但释放由 release_expired_blacklists 负责，
            # 本函数不改状态（故仍为 blacklisted）
            self.assertEqual(snapshot["days_remaining"], 0)
            self.assertTrue(snapshot["blacklisted"])
            self.assertIn("今天到期", snapshot["status_message"])


class TokenDigestTests(unittest.TestCase):
    """TC-U17～U18：token_digest（依据 NFR-02：会话令牌不得明文落库）"""

    def test_tc_u17_same_token_same_digest(self) -> None:
        token = "test-token-abc"
        self.assertEqual(app_main.token_digest(token), app_main.token_digest(token))

    def test_tc_u18_digest_is_sha256_hex(self) -> None:
        first = app_main.token_digest("token-a")
        second = app_main.token_digest("token-b")
        self.assertNotEqual(first, second)
        self.assertEqual(len(first), 64)
        int(first, 16)  # 必须是合法十六进制


class BearerTokenTests(unittest.TestCase):
    """TC-U19～U20：bearer_token（依据 NFR-02：未登录必须被拒）"""

    def test_tc_u19_valid_header_returns_token(self) -> None:
        self.assertEqual(app_main.bearer_token("Bearer abc123"), "abc123")
        # scheme 大小写不敏感
        self.assertEqual(app_main.bearer_token("bearer abc123"), "abc123")
        # 多余空格需被裁掉
        self.assertEqual(app_main.bearer_token("Bearer   abc123  "), "abc123")

    def test_tc_u20_missing_or_invalid_header_raises_401(self) -> None:
        for header in (None, "", "abc123", "Bearer", "Bearer ", "Basic abc123"):
            with self.subTest(header=header):
                with self.assertRaises(HTTPException) as ctx:
                    app_main.bearer_token(header)
                self.assertEqual(ctx.exception.status_code, 401)


# ============================================================================
# 集成测试（TC-I01～TC-I10）
#
# 与单元测试的区别：走真实 HTTP 与真实数据库（临时库），会话必须经
# POST /api/auth/login 取得，不手工插入 auth_sessions。
# 依据：01_需求规格说明书.md 的 AC-01／AC-09／AC-11、BR-11、BR-21
# ============================================================================

STUDENT_A = ("2024010201", "123456aa")  # 林知夏，种子数据 id=1
STUDENT_B = ("2024020816", "123456aa")  # 周予安，种子数据 id=2
BLACKLISTED_STUDENT = ("2023031108", "123456aa")  # 沈嘉木，种子数据已受限
ADMIN_CREDENTIAL = ("admin", "admin123456")


class PermissionApiTests(unittest.TestCase):
    """权限矩阵、投诉闭环与黑名单限制的接口级验证。"""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.db_patch = patch.object(app_main, "DB_PATH", self.db_path)
        self.db_patch.start()
        app_main.init_db()
        self.client = TestClient(app_main.app)

    def tearDown(self) -> None:
        self.client.close()
        self.db_patch.stop()
        self.temp_dir.cleanup()

    # ---- 夹具 ----
    def _db(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def _login(self, account: str, password: str, role: str = "student") -> dict[str, str]:
        response = self.client.post(
            "/api/auth/login",
            json={"account": account, "password": password, "role": role},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return {"Authorization": f"Bearer {response.json()['token']}"}

    def _login_admin(self) -> dict[str, str]:
        return self._login(*ADMIN_CREDENTIAL, role="admin")

    def _submit_complaint(self, headers: dict[str, str], category: str, subject: str) -> int:
        response = self.client.post(
            "/api/complaints",
            json={"user_id": 0, "category": category, "subject": subject, "content": "测试内容共十字以上"},
            headers=headers,
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["id"]

    # ---- TC-I01 管理员登录（复用既有证据的同类场景，此处独立验证） ----
    def test_tc_i01_admin_login_and_identity(self) -> None:
        headers = self._login_admin()
        me = self.client.get("/api/auth/me", headers=headers)
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["role"], "admin")

    # ---- TC-I02 学生登录 ----
    def test_tc_i02_student_login(self) -> None:
        student_no, password = STUDENT_A
        response = self.client.post(
            "/api/auth/login", json={"account": student_no, "password": password, "role": "student"}
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["role"], "student")
        self.assertEqual(body["account"], student_no)
        self.assertIn("token", body)

    # ---- TC-I03 匿名访问管理接口 → 401（NFR-02 / AC-11） ----
    def test_tc_i03_anonymous_rejected(self) -> None:
        cases = [
            ("get", "/api/users", None),
            ("get", "/api/overview", None),
            ("get", "/api/analytics", None),
            ("post", "/api/classrooms", {"name": "匿名教室", "floor": "一层"}),
        ]
        for method, url, payload in cases:
            with self.subTest(url=url):
                response = self.client.request(method.upper(), url, json=payload)
                self.assertEqual(response.status_code, 401, response.text)

    # ---- TC-I04 学生访问管理接口 → 403（BR-11 / AC-11） ----
    def test_tc_i04_student_on_admin_endpoint_rejected(self) -> None:
        headers = self._login(*STUDENT_A)
        cases = [
            ("get", "/api/users", None),
            ("patch", "/api/rooms/1/status", {"status": "maintenance", "note": "越权测试"}),
            ("post", "/api/users", {"name": "越权学生", "student_no": "2099000001", "phone": ""}),
            ("post", "/api/violations", {"user_id": 1, "reason": "越权登记"}),
        ]
        for method, url, payload in cases:
            with self.subTest(url=url):
                response = self.client.request(method.upper(), url, json=payload, headers=headers)
                self.assertEqual(response.status_code, 403, response.text)

    # ---- TC-I05 学生读他人数据 → 403（BR-11） ----
    def test_tc_i05_student_cannot_read_others(self) -> None:
        headers = self._login(*STUDENT_A)
        cases = [
            "/api/bookings?user_id=2",
            "/api/users/2/credit-profile",
            "/api/complaints?user_id=2",
        ]
        for url in cases:
            with self.subTest(url=url):
                response = self.client.get(url, headers=headers)
                self.assertEqual(response.status_code, 403, response.text)

    def test_tc_i05b_violation_query_does_not_leak_others(self) -> None:
        """安全不变量：学生无论如何构造参数，都不得拿到他人数据。

        本用例只守「不泄露」这一条铁律，不判断状态码语义——
        无论实现返回 200（静默过滤）还是 403（显式拒绝），只要不返回他人记录即通过。
        「越权读是否一律 403」属业务裁决（候选 BR-22），见 TC-I05c（skip）。
        """
        headers = self._login(*STUDENT_A)
        response = self.client.get("/api/violations?user_id=2", headers=headers)
        if response.status_code == 200:
            for item in response.json():
                self.assertEqual(item["user_id"], 1, "越权：返回了他人违约记录")
        else:
            self.assertEqual(response.status_code, 403, response.text)

    @unittest.skip("待裁决：越权读是否一律 403（候选 BR-22，业务确认人未定）")
    def test_tc_i05c_violation_query_should_return_403(self) -> None:
        """语义判定用例：裁定为「一律 403」后移除 skip，本用例应通过。

        现状不一致（2026-11-26 记录）：
          /api/bookings?user_id=2        → 403
          /api/users/2/credit-profile    → 403
          /api/complaints?user_id=2      → 403
          /api/violations?user_id=2      → 200 + 本人数据（静默忽略参数）
        """
        headers = self._login(*STUDENT_A)
        response = self.client.get("/api/violations?user_id=2", headers=headers)
        self.assertEqual(response.status_code, 403, response.text)

    # ---- TC-I06 投诉四类提交（FR-12） ----
    def test_tc_i06_four_feedback_categories(self) -> None:
        headers = self._login(*STUDENT_A)
        for category in ("投诉", "报修", "建议", "申诉"):
            with self.subTest(category=category):
                complaint_id = self._submit_complaint(
                    headers, category, f"{category}主题测试"
                )
                db = self._db()
                row = db.execute(
                    "SELECT category, status FROM complaints WHERE id = ?", (complaint_id,)
                ).fetchone()
                db.close()
                self.assertEqual(row["category"], category)
                self.assertEqual(row["status"], "待处理")

    # ---- TC-I07 学生只看到本人投诉（BR-11） ----
    def test_tc_i07_student_sees_only_own_complaints(self) -> None:
        headers_a = self._login(*STUDENT_A)
        headers_b = self._login(*STUDENT_B)
        self._submit_complaint(headers_a, "投诉", "甲同学的投诉记录")

        mine = self.client.get("/api/complaints", headers=headers_a)
        self.assertEqual(mine.status_code, 200)
        self.assertTrue(mine.json(), "本人应有至少一条投诉")
        self.assertTrue(all(item["user_id"] == 1 for item in mine.json()))

        others = self.client.get("/api/complaints", headers=headers_b)
        self.assertEqual(others.status_code, 200)
        subjects = [item["subject"] for item in others.json()]
        self.assertNotIn("甲同学的投诉记录", subjects)

    # ---- TC-I08 管理员回复投诉，学生可见（AC-09） ----
    def test_tc_i08_admin_reply_visible_to_student(self) -> None:
        headers_student = self._login(*STUDENT_A)
        headers_admin = self._login_admin()
        complaint_id = self._submit_complaint(headers_student, "建议", "希望延长开放时间")

        reply = self.client.patch(
            f"/api/complaints/{complaint_id}",
            json={"status": "已完成", "reply": "已反馈后勤，下月起延长至 22:30"},
            headers=headers_admin,
        )
        self.assertEqual(reply.status_code, 200, reply.text)

        listed = self.client.get("/api/complaints", headers=headers_student)
        self.assertEqual(listed.status_code, 200)
        target = next(item for item in listed.json() if item["id"] == complaint_id)
        self.assertEqual(target["status"], "已完成")
        self.assertIn("延长至 22:30", target["reply"])

    # ---- TC-I09 黑名单到期自动释放（FR-14：到期自动恢复） ----
    def test_tc_i09_expired_blacklist_is_released(self) -> None:
        headers_admin = self._login_admin()
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        created = self.client.post(
            "/api/users",
            json={
                "name": "到期受限学生",
                "student_no": "2099000011",
                "phone": "",
                "blacklisted": True,
                "blacklisted_until": yesterday,
                "blacklist_reason": "测试到期释放",
            },
            headers=headers_admin,
        )
        self.assertEqual(created.status_code, 200, created.text)

        # 登录会触发 release_expired_blacklists，到期限制应被解除
        login = self.client.post(
            "/api/auth/login",
            json={"account": "2099000011", "password": "123456aa", "role": "student"},
        )
        self.assertEqual(login.status_code, 200, login.text)
        self.assertFalse(login.json()["blacklisted"], "到期后不应再受限")

        db = self._db()
        row = db.execute(
            "SELECT blacklisted, blacklisted_until FROM users WHERE student_no = '2099000011'"
        ).fetchone()
        db.close()
        self.assertEqual(row["blacklisted"], 0)
        self.assertIsNone(row["blacklisted_until"])

    # ---- TC-I10 修改密码后其他会话失效（FR-01，原卡用例如实保留） ----
    def test_tc_i10_password_change_invalidates_other_sessions(self) -> None:
        student_no, password = STUDENT_A
        first = self.client.post(
            "/api/auth/login", json={"account": student_no, "password": password, "role": "student"}
        )
        self.assertEqual(first.status_code, 200, first.text)
        user_id = first.json()["id"]
        headers_first = {"Authorization": f"Bearer {first.json()['token']}"}

        second = self.client.post(
            "/api/auth/login", json={"account": student_no, "password": password, "role": "student"}
        )
        self.assertEqual(second.status_code, 200, second.text)
        headers_second = {"Authorization": f"Bearer {second.json()['token']}"}

        changed = self.client.patch(
            f"/api/users/{user_id}/password",
            json={"old_password": password, "new_password": "newpass123"},
            headers=headers_first,
        )
        self.assertEqual(changed.status_code, 200, changed.text)

        # 其他会话必须失效
        self.assertEqual(self.client.get("/api/auth/me", headers=headers_second).status_code, 401)
        # 发起改密的当前会话保留
        self.assertEqual(self.client.get("/api/auth/me", headers=headers_first).status_code, 200)

    # ---- TC-I11 黑名单未填解封日期 → 拒绝（BR-21，补充用例，尚未实现） ----
    @unittest.expectedFailure
    def test_tc_i11_blacklist_requires_unban_date(self) -> None:
        """BR-21：强制填写解封日期，不填拒绝提交。

        当前实现：空值走 default_blacklist_until() 补 7 天，返回 200 → 与决定不符。
        BR-21 实现后本用例应通过，届时移除 expectedFailure 标记。
        """
        headers_admin = self._login_admin()
        response = self.client.post(
            "/api/users",
            json={
                "name": "无解封日期学生",
                "student_no": "2099000002",
                "phone": "",
                "blacklisted": True,
            },
            headers=headers_admin,
        )
        self.assertEqual(response.status_code, 400, response.text)

    # ---- TC-I12 受限账号创建预约 → 403（BR-11，补充用例，现实现为 400） ----
    @unittest.expectedFailure
    def test_tc_i12_blacklisted_cannot_book_returns_403(self) -> None:
        """BR-11 修正后的语义：权限不足应返回 403。

        当前实现：create_booking 内抛 400 并附解封天数 → 与决定不符。
        改为 403 后本用例应通过，届时移除 expectedFailure 标记。
        """
        headers = self._login(*BLACKLISTED_STUDENT)
        response = self.client.post(
            "/api/bookings",
            json={"user_id": 0, "room_id": 1, "start_at": "2031-02-04 09:00", "end_at": "2031-02-04 11:00"},
            headers=headers,
        )
        self.assertEqual(response.status_code, 403, response.text)


if __name__ == "__main__":
    unittest.main()
