# -*- coding: utf-8 -*-
"""TASK-002 预约与座位测试：20 个单元 + 10 个集成。

预期结果出处：01_需求规格说明书.md v2.0 的 FR/BR/AC/ST 编号（不从代码倒推）。
单元测试直接调用函数（不经过 HTTP 路由），集成测试用 TestClient 走完整请求链路。
被测代码版本：仓库提交 c8bd36f。
"""

from __future__ import annotations

import re
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import main as app_main
from app.main import (
    AuthContext,
    BookingCreate,
    SeatStatusPayload,
    calculate_credit_rating,
    create_booking,
    now_text,
    rows_to_dict,
    sync_classroom_capacities,
    update_booking_status,
    update_room_status,
)

ADMIN_HEADERS = {"Authorization": "Bearer zj-admin-token"}
STUDENT1_HEADERS = {"Authorization": "Bearer zj-student1-token"}
STUDENT2_HEADERS = {"Authorization": "Bearer zj-student2-token"}

ADMIN_CTX = AuthContext(role="admin", account="admin", name="林管理员")
STUDENT1_CTX = AuthContext(role="student", account="2024010201", name="林知夏", user_id=1)


def fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")


class _BaseCase(unittest.TestCase):
    """公共夹具：每个用例独立临时库，不触碰真实 study_room.db。"""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = Path(self.temp_dir.name) / "task002.db"
        self.db_patch = patch.object(app_main, "DB_PATH", self.db_path)
        self.db_patch.start()
        app_main.init_db()

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def _insert_booking(
        self,
        user_id: int = 1,
        room_id: int = 1,
        status: str = "booked",
        start_min: int = -5,
        end_min: int = 60,
    ) -> int:
        now = datetime.now()
        db = self._connect()
        cursor = db.execute(
            "INSERT INTO bookings(user_id, room_id, start_at, end_at, status, source, created_at) "
            "VALUES (?, ?, ?, ?, ?, 'user', ?)",
            (user_id, room_id, fmt(now + timedelta(minutes=start_min)),
             fmt(now + timedelta(minutes=end_min)), status, now_text()),
        )
        db.commit()
        booking_id = int(cursor.lastrowid)
        db.close()
        return booking_id

    def _room_status(self, room_id: int) -> str:
        db = self._connect()
        row = db.execute("SELECT status FROM rooms WHERE id = ?", (room_id,)).fetchone()
        db.close()
        return row["status"]

    def _booking_row(self, booking_id: int) -> sqlite3.Row:
        db = self._connect()
        row = db.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
        db.close()
        return row

    def _booking_count(self, room_id: int) -> int:
        db = self._connect()
        count = db.execute(
            "SELECT COUNT(*) FROM bookings WHERE room_id = ? AND status IN ('booked','checked_in')",
            (room_id,),
        ).fetchone()[0]
        db.close()
        return count


class BookingCreateValidationUnitTests(_BaseCase):
    """单元 1~5：create_booking 的入口校验（FR-04、BR-03、BR-11）。"""

    def test_u01_create_booking_user_not_found(self) -> None:
        """TC-Z01 用户不存在 → 404（FR-04：校验用户资格）。"""
        payload = BookingCreate(user_id=999, room_id=1, start_at="2027-01-05 10:00", end_at="2027-01-05 11:00")
        with self.assertRaises(HTTPException) as ctx:
            create_booking(payload, ADMIN_CTX)
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertIn("不存在", str(ctx.exception.detail))

    def test_u02_create_booking_room_not_found(self) -> None:
        """TC-Z02 座位不存在 → 404（FR-04）。"""
        payload = BookingCreate(user_id=1, room_id=9999, start_at="2027-01-05 10:00", end_at="2027-01-05 11:00")
        with self.assertRaises(HTTPException) as ctx:
            create_booking(payload, ADMIN_CTX)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_u03_create_booking_room_not_open(self) -> None:
        """TC-Z03 座位处于维修中 → 409（BR-03）。seed 数据里 6 号座位为 maintenance。"""
        self.assertEqual(self._room_status(6), "maintenance")
        payload = BookingCreate(user_id=1, room_id=6, start_at="2027-01-05 10:00", end_at="2027-01-05 11:00")
        with self.assertRaises(HTTPException) as ctx:
            create_booking(payload, ADMIN_CTX)
        self.assertEqual(ctx.exception.status_code, 409)

    def test_u04_create_booking_blacklisted_user(self) -> None:
        """TC-Z04 受限账号不可新建预约 → 400（BR-11、FR-14）。seed 数据里 3 号学生受限。"""
        payload = BookingCreate(user_id=3, room_id=1, start_at="2027-01-05 10:00", end_at="2027-01-05 11:00")
        with self.assertRaises(HTTPException) as ctx:
            create_booking(payload, ADMIN_CTX)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("受限", str(ctx.exception.detail))

    def test_u05_create_booking_bad_time_format(self) -> None:
        """TC-Z05 时间格式错误 → 400（FR-04、BR-14）。"""
        payload = BookingCreate(user_id=1, room_id=1, start_at="明天上午", end_at="2027-01-05 11:00")
        with self.assertRaises(HTTPException) as ctx:
            create_booking(payload, ADMIN_CTX)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("时间格式", str(ctx.exception.detail))


class BookingStateMachineUnitTests(_BaseCase):
    """单元 6~11：update_booking_status 状态机（ST-01~ST-09）。"""

    def test_u06_transition_booked_to_checked_in(self) -> None:
        """TC-Z06 合法迁移①：已预约 → 使用中（ST-03 签到）。"""
        booking_id = self._insert_booking(room_id=1, status="booked", start_min=-5, end_min=60)
        update_booking_status(booking_id, "checked_in", STUDENT1_CTX)
        row = self._booking_row(booking_id)
        self.assertEqual(row["status"], "checked_in")
        self.assertIsNotNone(row["checked_in_at"])
        self.assertEqual(self._room_status(1), "occupied")  # ST-10

    def test_u07_transition_booked_to_cancelled(self) -> None:
        """TC-Z07 合法迁移②：已预约 → 已取消（ST-02 学生取消）。"""
        booking_id = self._insert_booking(room_id=2, status="booked", start_min=60, end_min=120)
        update_booking_status(booking_id, "cancelled", STUDENT1_CTX)
        self.assertEqual(self._booking_row(booking_id)["status"], "cancelled")

    def test_u08_transition_booked_to_violation(self) -> None:
        """TC-Z08 合法迁移③：已预约 → 违约（ST-04 宽限期届满未签到）。"""
        booking_id = self._insert_booking(room_id=2, status="booked", start_min=-120, end_min=-60)
        db = self._connect()
        before = db.execute("SELECT violations FROM users WHERE id = 1").fetchone()["violations"]
        db.close()
        update_booking_status(booking_id, "violation", ADMIN_CTX)
        db = self._connect()
        after = db.execute("SELECT violations FROM users WHERE id = 1").fetchone()["violations"]
        db.close()
        self.assertEqual(self._booking_row(booking_id)["status"], "violation")
        self.assertEqual(after, before + 1)  # BR-07 登记一次违约

    def test_u09_transition_checked_in_to_completed(self) -> None:
        """TC-Z09 合法迁移④：使用中 → 已完成（ST-05 签退）。"""
        booking_id = self._insert_booking(room_id=4, status="checked_in", start_min=-15, end_min=45)
        db = self._connect()
        db.execute("UPDATE rooms SET status = 'occupied' WHERE id = 4")
        db.commit()
        db.close()
        update_booking_status(booking_id, "completed", STUDENT1_CTX)
        row = self._booking_row(booking_id)
        self.assertEqual(row["status"], "completed")
        self.assertIsNotNone(row["checked_out_at"])
        self.assertGreater(row["early_minutes"], 0)  # BR-08 记录提前分钟
        self.assertEqual(self._room_status(4), "open")  # ST-11

    def test_u10_transition_checked_in_to_violation(self) -> None:
        """TC-Z10 合法迁移⑤：使用中 → 违约（ST-06 管理员判定使用异常）。"""
        booking_id = self._insert_booking(room_id=4, status="checked_in", start_min=-15, end_min=45)
        db = self._connect()
        db.execute("UPDATE rooms SET status = 'occupied' WHERE id = 4")
        db.commit()
        db.close()
        update_booking_status(booking_id, "violation", ADMIN_CTX)
        self.assertEqual(self._booking_row(booking_id)["status"], "violation")
        self.assertEqual(self._room_status(4), "open")

    def test_u11_illegal_transitions_rejected(self) -> None:
        """TC-Z11 非法迁移拒绝：ST-08 已完成 → 已预约；ST-09 已取消 → 使用中。"""
        done_id = self._insert_booking(room_id=2, status="completed", start_min=-120, end_min=-60)
        with self.assertRaises(HTTPException) as ctx1:
            update_booking_status(done_id, "booked", ADMIN_CTX)
        self.assertEqual(ctx1.exception.status_code, 409)

        cancelled_id = self._insert_booking(room_id=2, status="cancelled", start_min=60, end_min=120)
        with self.assertRaises(HTTPException) as ctx2:
            update_booking_status(cancelled_id, "checked_in", STUDENT1_CTX)
        self.assertEqual(ctx2.exception.status_code, 409)

        # 终态记录不得被改动（BR-05）
        self.assertEqual(self._booking_row(done_id)["status"], "completed")
        self.assertEqual(self._booking_row(cancelled_id)["status"], "cancelled")


class RoomStatusUnitTests(_BaseCase):
    """单元 12~15：update_room_status 的枚举、报修与恢复条件（FR-09、BR-04、ST-12/13）。"""

    def test_u12_room_status_enum_rejected(self) -> None:
        """TC-Z12 手动切换只允许 open/maintenance → 400。"""
        with self.assertRaises(HTTPException) as ctx:
            update_room_status(1, SeatStatusPayload(status="occupied"), ADMIN_CTX)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_u13_maintenance_rejected_when_occupied(self) -> None:
        """TC-Z13 使用中座位不可报修 → 409（BR-04 的反向：座位正在使用）。"""
        self.assertEqual(self._room_status(3), "occupied")
        with self.assertRaises(HTTPException) as ctx:
            update_room_status(3, SeatStatusPayload(status="maintenance", note="报修测试"), ADMIN_CTX)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("使用中", str(ctx.exception.detail))

    def test_u14_maintenance_rejected_with_active_booking(self) -> None:
        """TC-Z14 有未结束预约不可报修 → 409（BR-04、AC-07）。"""
        self._insert_booking(user_id=2, room_id=2, status="booked", start_min=60, end_min=120)
        with self.assertRaises(HTTPException) as ctx:
            update_room_status(2, SeatStatusPayload(status="maintenance", note="报修测试"), ADMIN_CTX)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("未结束预约", str(ctx.exception.detail))
        self.assertEqual(self._room_status(2), "open")  # 拒绝后状态不变

    def test_u15_restore_conditions(self) -> None:
        """TC-Z15 恢复条件：维修中可恢复（ST-13）；使用中不可恢复（409）。"""
        self.assertEqual(self._room_status(6), "maintenance")
        update_room_status(6, SeatStatusPayload(status="open", note="维修完成"), ADMIN_CTX)
        self.assertEqual(self._room_status(6), "open")

        with self.assertRaises(HTTPException) as ctx:
            update_room_status(3, SeatStatusPayload(status="open", note="强制恢复"), ADMIN_CTX)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(self._room_status(3), "occupied")


class PureFunctionUnitTests(_BaseCase):
    """单元 16~20：容量汇总、行转换、时间格式、信用分交叉复核。"""

    def test_u16_sync_classroom_capacity_counts_rooms(self) -> None:
        """TC-Z16 教室容量等于其下座位数（BR-12）。"""
        db = self._connect()
        sync_classroom_capacities(db)
        db.commit()
        capacity = db.execute("SELECT capacity FROM classrooms WHERE id = 1").fetchone()[0]
        db.close()
        self.assertEqual(capacity, 4)  # 一层 4 个座位

        db = self._connect()
        db.execute(
            "INSERT INTO rooms(name, classroom_id, floor, capacity, status, features, created_at) "
            "VALUES ('A-05', 1, '一层·安静区', 1, 'open', '新增测试座位', ?)",
            (now_text(),),
        )
        db.commit()
        sync_classroom_capacities(db)
        db.commit()
        capacity = db.execute("SELECT capacity FROM classrooms WHERE id = 1").fetchone()[0]
        db.close()
        self.assertEqual(capacity, 5)

    def test_u17_sync_classroom_status_all_maintenance(self) -> None:
        """TC-Z17 全部座位维修 → 教室维修中；存在非维修座位 → 开放（BR-13）。"""
        db = self._connect()
        db.execute("UPDATE rooms SET status = 'maintenance' WHERE classroom_id = 1")
        db.commit()
        sync_classroom_capacities(db)
        db.commit()
        status = db.execute("SELECT status FROM classrooms WHERE id = 1").fetchone()[0]
        db.close()
        self.assertEqual(status, "maintenance")

        db = self._connect()
        db.execute("UPDATE rooms SET status = 'open' WHERE id = 1")
        db.commit()
        sync_classroom_capacities(db)
        db.commit()
        status = db.execute("SELECT status FROM classrooms WHERE id = 1").fetchone()[0]
        db.close()
        self.assertEqual(status, "open")

    def test_u18_rows_to_dict(self) -> None:
        """TC-Z18 行转换：空列表返回 []；正常数据返回 dict 列表。"""
        self.assertEqual(rows_to_dict([]), [])
        db = self._connect()
        rows = db.execute("SELECT id, name, status FROM rooms ORDER BY id LIMIT 3").fetchall()
        db.close()
        result = rows_to_dict(rows)
        self.assertEqual(len(result), 3)
        self.assertIsInstance(result[0], dict)
        self.assertEqual(set(result[0].keys()), {"id", "name", "status"})

    def test_u19_now_text_format(self) -> None:
        """TC-Z19 时间文本符合 YYYY-MM-DD HH:MM（BR-14 时间格式约束）。"""
        value = now_text()
        self.assertRegex(value, r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
        datetime.strptime(value, "%Y-%m-%d %H:%M")  # 可解析即通过

    def test_u20_credit_rating_cross_check(self) -> None:
        """TC-Z20 信用分交叉复核（BR-09）：换角度断言单调性与下限。"""
        self.assertEqual(calculate_credit_rating(0), 5.0)
        self.assertEqual(calculate_credit_rating(1), 4.6)
        self.assertEqual(calculate_credit_rating(10), 1.0)
        self.assertEqual(calculate_credit_rating(100), 1.0)  # 下限 1.0
        scores = [calculate_credit_rating(n) for n in range(12)]
        self.assertEqual(scores, sorted(scores, reverse=True))  # 单调不增
        self.assertEqual(round(scores[0] - scores[1], 2), 0.4)  # 每次固定扣 0.4


class BookingFlowIntegrationTests(_BaseCase):
    """集成 1~10：走完整 HTTP 链路（路由 + 校验 + 数据库）。"""

    def setUp(self) -> None:
        super().setUp()
        self.client = TestClient(app_main.app)
        self._seed_sessions()

    def tearDown(self) -> None:
        self.client.close()
        super().tearDown()

    def _seed_sessions(self) -> None:
        now = int(app_main.time())
        db = self._connect()
        db.executemany(
            "INSERT INTO auth_sessions(token_hash, role, user_id, account, name, expires_at, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (app_main.token_digest("zj-admin-token"), "admin", None, "admin", "林管理员",
                 now + 3600, now_text()),
                (app_main.token_digest("zj-student1-token"), "student", 1, "2024010201", "林知夏",
                 now + 3600, now_text()),
                (app_main.token_digest("zj-student2-token"), "student", 2, "2024020816", "周予安",
                 now + 3600, now_text()),
            ],
        )
        db.commit()
        db.close()

    def test_i01_create_booking_success(self) -> None:
        """TC-Z21 创建预约成功（AC-02、ST-01）。座位状态按 BR-16 语义不因预约改变。"""
        tomorrow = datetime.now() + timedelta(days=1)
        response = self.client.post(
            "/api/bookings",
            json={"user_id": 1, "room_id": 2,
                  "start_at": fmt(tomorrow.replace(hour=10, minute=0)),
                  "end_at": fmt(tomorrow.replace(hour=11, minute=0))},
            headers=STUDENT1_HEADERS,
        )
        self.assertEqual(response.status_code, 200)
        booking_id = response.json()["id"]
        row = self._booking_row(booking_id)
        self.assertEqual(row["status"], "booked")
        self.assertEqual(row["user_id"], 1)
        self.assertEqual(row["source"], "user")
        self.assertEqual(self._room_status(2), "open")  # BR-16：占用状态在签到时才改变

    def test_i02_overlap_conflict(self) -> None:
        """TC-Z22 时段冲突（AC-03、BR-01）：返回冲突且不生成记录。"""
        tomorrow = (datetime.now() + timedelta(days=1)).replace(hour=10, minute=0)
        payload = {"user_id": 1, "room_id": 2, "start_at": fmt(tomorrow),
                   "end_at": fmt(tomorrow + timedelta(hours=1))}
        first = self.client.post("/api/bookings", json=payload, headers=STUDENT1_HEADERS)
        self.assertEqual(first.status_code, 200)
        second = self.client.post(
            "/api/bookings",
            json={"user_id": 2, "room_id": 2, "start_at": fmt(tomorrow + timedelta(minutes=30)),
                  "end_at": fmt(tomorrow + timedelta(hours=2))},
            headers=STUDENT2_HEADERS,
        )
        self.assertEqual(second.status_code, 409)
        self.assertEqual(self._booking_count(2), 1)

    def test_i03_cancel_releases_slot(self) -> None:
        """TC-Z23 取消释放座位（AC-04、ST-02、BR-06）。"""
        tomorrow = (datetime.now() + timedelta(days=1)).replace(hour=14, minute=0)
        created = self.client.post(
            "/api/bookings",
            json={"user_id": 1, "room_id": 4, "start_at": fmt(tomorrow),
                  "end_at": fmt(tomorrow + timedelta(hours=1))},
            headers=STUDENT1_HEADERS,
        )
        booking_id = created.json()["id"]
        cancelled = self.client.patch(
            f"/api/bookings/{booking_id}/status?status=cancelled", headers=STUDENT1_HEADERS
        )
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(self._booking_row(booking_id)["status"], "cancelled")

        rebooked = self.client.post(
            "/api/bookings",
            json={"user_id": 2, "room_id": 4, "start_at": fmt(tomorrow),
                  "end_at": fmt(tomorrow + timedelta(hours=1))},
            headers=STUDENT2_HEADERS,
        )
        self.assertEqual(rebooked.status_code, 200)

    def test_i04_checkin_occupies_seat(self) -> None:
        """TC-Z24 签到后座位置为使用中（ST-03、ST-10）。"""
        now = datetime.now()
        created = self.client.post(
            "/api/bookings",
            json={"user_id": 1, "room_id": 1, "start_at": fmt(now - timedelta(minutes=5)),
                  "end_at": fmt(now + timedelta(minutes=60))},
            headers=STUDENT1_HEADERS,
        )
        booking_id = created.json()["id"]
        checked = self.client.patch(
            f"/api/bookings/{booking_id}/status?status=checked_in", headers=STUDENT1_HEADERS
        )
        self.assertEqual(checked.status_code, 200)
        self.assertEqual(self._booking_row(booking_id)["status"], "checked_in")
        self.assertEqual(self._room_status(1), "occupied")

    def test_i05_checkout_restores_seat(self) -> None:
        """TC-Z25 签退恢复座位（AC-06、ST-05、ST-11）。"""
        now = datetime.now()
        created = self.client.post(
            "/api/bookings",
            json={"user_id": 1, "room_id": 1, "start_at": fmt(now - timedelta(minutes=10)),
                  "end_at": fmt(now + timedelta(minutes=50))},
            headers=STUDENT1_HEADERS,
        )
        booking_id = created.json()["id"]
        self.client.patch(f"/api/bookings/{booking_id}/status?status=checked_in", headers=STUDENT1_HEADERS)
        checked_out = self.client.patch(
            f"/api/bookings/{booking_id}/status?status=completed", headers=STUDENT1_HEADERS
        )
        self.assertEqual(checked_out.status_code, 200)
        row = self._booking_row(booking_id)
        self.assertEqual(row["status"], "completed")
        self.assertGreater(row["early_minutes"], 0)
        self.assertEqual(self._room_status(1), "open")

    def test_i06_maintenance_seat_not_bookable(self) -> None:
        """TC-Z26 维修座位不可预约（BR-03）。"""
        tomorrow = datetime.now() + timedelta(days=1)
        response = self.client.post(
            "/api/bookings",
            json={"user_id": 1, "room_id": 6, "start_at": fmt(tomorrow.replace(hour=10, minute=0)),
                  "end_at": fmt(tomorrow.replace(hour=11, minute=0))},
            headers=STUDENT1_HEADERS,
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self._booking_count(6), 0)

    def test_i07_cannot_report_maintenance_with_active_booking(self) -> None:
        """TC-Z27 有活动预约不可报修（AC-07、BR-04）。"""
        now = datetime.now()
        self.client.post(
            "/api/bookings",
            json={"user_id": 1, "room_id": 2, "start_at": fmt(now + timedelta(minutes=30)),
                  "end_at": fmt(now + timedelta(minutes=90))},
            headers=STUDENT1_HEADERS,
        )
        response = self.client.patch(
            "/api/rooms/2/status", json={"status": "maintenance", "note": "报修"}, headers=ADMIN_HEADERS
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn("未结束预约", response.json()["detail"])
        self.assertEqual(self._room_status(2), "open")

    def test_i08_restore_after_repair(self) -> None:
        """TC-Z28 维修完成恢复（AC-08、ST-13）。"""
        restored = self.client.patch(
            "/api/rooms/6/status", json={"status": "open", "note": "维修完成"}, headers=ADMIN_HEADERS
        )
        self.assertEqual(restored.status_code, 200)
        self.assertEqual(self._room_status(6), "open")

        tomorrow = datetime.now() + timedelta(days=1)
        booking = self.client.post(
            "/api/bookings",
            json={"user_id": 1, "room_id": 6, "start_at": fmt(tomorrow.replace(hour=15, minute=0)),
                  "end_at": fmt(tomorrow.replace(hour=16, minute=0))},
            headers=STUDENT1_HEADERS,
        )
        self.assertEqual(booking.status_code, 200)

    def test_i09_concurrent_bookings_100_threads(self) -> None:
        """TC-Z29 并发抢座 100 线程（AC-12、BR-01）：只成功一条。"""
        tomorrow = (datetime.now() + timedelta(days=2)).replace(hour=9, minute=0)
        start_at, end_at = fmt(tomorrow), fmt(tomorrow + timedelta(hours=1))
        worker_count = 100
        barrier = threading.Barrier(worker_count)

        def attempt(index: int) -> int:
            client = TestClient(app_main.app)
            try:
                barrier.wait(timeout=30)
                response = client.post(
                    "/api/bookings",
                    json={"user_id": 1 if index % 2 == 0 else 2, "room_id": 2,
                          "start_at": start_at, "end_at": end_at},
                    headers=STUDENT1_HEADERS if index % 2 == 0 else STUDENT2_HEADERS,
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
            "SELECT COUNT(*) FROM bookings WHERE room_id = 2 AND status IN ('booked','checked_in') "
            "AND start_at < ? AND end_at > ?",
            (end_at, start_at),
        ).fetchone()[0]
        db.close()
        self.assertEqual(count, 1)

    def test_i10_room_query_and_filter(self) -> None:
        """TC-Z30 座位筛选查询（FR-03）：返回可筛选字段，按状态过滤结果自洽。"""
        response = self.client.get("/api/rooms", headers=STUDENT1_HEADERS)
        self.assertEqual(response.status_code, 200)
        rooms = response.json()
        self.assertGreater(len(rooms), 0)
        required = {"id", "name", "classroom_name", "status", "status_label", "features"}
        self.assertTrue(required.issubset(set(rooms[0].keys())))

        labels = {"open": "可预约", "occupied": "使用中", "maintenance": "维修中"}
        for room in rooms:
            self.assertIn(room["status"], labels)
            self.assertEqual(room["status_label"], labels[room["status"]])

        open_rooms = [room for room in rooms if room["status"] == "open"]
        self.assertEqual(len(open_rooms), sum(1 for room in rooms if room["status_label"] == "可预约"))
        self.assertGreater(len(open_rooms), 0)


if __name__ == "__main__":
    unittest.main()
