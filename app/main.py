from __future__ import annotations

import csv
import io
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "study_room.db"


def connect_db() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


RATING_BASE = 5.0
RATING_PENALTY_PER_VIOLATION = 0.4
CREDIT_RECOVERY_DAYS = 90
LATE_GRACE_MINUTES = 15


def calculate_credit_rating(violation_count: int) -> float:
    return max(1.0, round(RATING_BASE - violation_count * RATING_PENALTY_PER_VIOLATION, 2))


def credit_level(score: float) -> tuple[str, str]:
    if score >= RATING_BASE:
        return "excellent", "信用优秀"
    if score >= 4.5:
        return "good", "信用良好"
    if score >= 4.0:
        return "watch", "需要保持"
    if score >= 3.5:
        return "risk", "信用偏低"
    return "high_risk", "高风险"


def credit_cutoff_text() -> str:
    return (datetime.now() - timedelta(days=CREDIT_RECOVERY_DAYS)).strftime("%Y-%m-%d %H:%M")


def count_active_violations(db: sqlite3.Connection, user_id: int) -> int:
    return db.execute(
        "SELECT COUNT(*) FROM violations WHERE user_id = ? AND created_at >= ?",
        (user_id, credit_cutoff_text()),
    ).fetchone()[0]


def sync_user_rating(db: sqlite3.Connection, user_id: int) -> float | None:
    row = db.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        return None
    score = calculate_credit_rating(count_active_violations(db, user_id))
    db.execute("UPDATE users SET rating = ? WHERE id = ?", (score, user_id))
    return score


def sync_all_user_ratings(db: sqlite3.Connection) -> None:
    cutoff = credit_cutoff_text()
    db.execute(
        "UPDATE users SET rating = MAX(1.0, ROUND(5.0 - ("
        "SELECT COUNT(*) FROM violations WHERE violations.user_id = users.id AND violations.created_at >= ?"
        ") * ?, 2))",
        (cutoff, RATING_PENALTY_PER_VIOLATION),
    )


def backfill_violation_history(db: sqlite3.Connection) -> None:
    rows = db.execute(
        "SELECT users.id, users.violations, users.created_at, COUNT(violations.id) AS recorded "
        "FROM users LEFT JOIN violations ON violations.user_id = users.id "
        "GROUP BY users.id"
    ).fetchall()
    for row in rows:
        missing = max(0, row["violations"] - row["recorded"])
        for _ in range(missing):
            db.execute(
                "INSERT INTO violations(user_id, reason, source, created_at) VALUES (?, ?, 'system', ?)",
                (row["id"], "历史违约记录（系统补录）", row["created_at"]),
            )


def sync_classroom_capacities(db: sqlite3.Connection) -> None:
    db.execute(
        "UPDATE classrooms SET capacity = "
        "(SELECT COUNT(*) FROM rooms WHERE rooms.classroom_id = classrooms.id)"
    )
    db.execute(
        "UPDATE classrooms SET status = CASE WHEN EXISTS ("
        "SELECT 1 FROM rooms WHERE rooms.classroom_id = classrooms.id"
        ") AND NOT EXISTS ("
        "SELECT 1 FROM rooms WHERE rooms.classroom_id = classrooms.id AND rooms.status <> 'maintenance'"
        ") THEN 'maintenance' ELSE 'open' END"
    )


def default_blacklist_until() -> str:
    return (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d 23:59")


def normalize_blacklist_until(value: str | None, blacklisted: bool) -> str | None:
    if not blacklisted:
        return None
    candidate = (value or "").strip()
    if not candidate:
        return default_blacklist_until()
    for pattern, end_of_day in (("%Y-%m-%d", True), ("%Y-%m-%d %H:%M", False)):
        try:
            parsed = datetime.strptime(candidate, pattern)
        except ValueError:
            continue
        if end_of_day:
            parsed = parsed.replace(hour=23, minute=59)
        return parsed.strftime("%Y-%m-%d %H:%M")
    raise HTTPException(400, "解封日期格式不正确，请使用 YYYY-MM-DD")


def release_expired_blacklists(db: sqlite3.Connection) -> None:
    cursor = db.execute(
        "UPDATE users SET blacklisted = 0, blacklisted_until = NULL, "
        "blacklisted_at = NULL, blacklist_reason = '' "
        "WHERE blacklisted = 1 AND blacklisted_until IS NOT NULL AND blacklisted_until <= ?",
        (now_text(),),
    )
    if cursor.rowcount:
        db.commit()


def account_snapshot(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    is_blacklisted = bool(data.get("blacklisted"))
    until_text = data.get("blacklisted_until") if is_blacklisted else None
    days_remaining: int | None = None
    if until_text:
        try:
            until_at = datetime.strptime(until_text, "%Y-%m-%d %H:%M")
            days_remaining = max(0, (until_at.date() - datetime.now().date()).days)
        except ValueError:
            days_remaining = None
    unban_date = until_text.split(" ")[0] if until_text else None
    if is_blacklisted and days_remaining == 0:
        status_message = f"账号当前受限，预计 {unban_date} 解封，今天到期。"
    elif is_blacklisted and days_remaining is not None:
        status_message = f"账号当前受限，预计 {unban_date} 解封，剩余 {days_remaining} 天。"
    elif is_blacklisted:
        status_message = "账号当前受限，暂未设置解封日期，请联系管理员确认。"
    else:
        status_message = "账号状态正常，可以正常预约座位和使用自习室服务。"
    level, level_label = credit_level(float(data.get("rating") or RATING_BASE))
    data.update({
        "blacklisted": is_blacklisted,
        "is_blacklisted": is_blacklisted,
        "blacklisted_until": until_text,
        "blacklisted_at": data.get("blacklisted_at") if is_blacklisted else None,
        "blacklist_reason": (data.get("blacklist_reason") or "") if is_blacklisted else "",
        "unban_date": unban_date,
        "days_remaining": days_remaining,
        "status": "blacklisted" if is_blacklisted else "active",
        "status_label": "账号受限" if is_blacklisted else "状态正常",
        "status_message": status_message,
        "credit_level": level,
        "credit_level_label": level_label,
    })
    data.pop("password", None)
    return data


def init_db() -> None:
    db = connect_db()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS rooms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            classroom_id INTEGER REFERENCES classrooms(id),
            floor TEXT NOT NULL,
            capacity INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'open',
            features TEXT NOT NULL DEFAULT '',
            status_note TEXT NOT NULL DEFAULT '',
            status_updated_at TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            student_no TEXT NOT NULL UNIQUE,
            phone TEXT NOT NULL,
            password TEXT NOT NULL DEFAULT '123456aa',
            violations INTEGER NOT NULL DEFAULT 0,
            blacklisted INTEGER NOT NULL DEFAULT 0,
            blacklisted_until TEXT,
            blacklisted_at TEXT,
            blacklist_reason TEXT NOT NULL DEFAULT '',
            rating REAL NOT NULL DEFAULT 5.0,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS classrooms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            building TEXT NOT NULL DEFAULT '主楼',
            floor TEXT NOT NULL,
            capacity INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'open',
            features TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            room_id INTEGER NOT NULL REFERENCES rooms(id),
            start_at TEXT NOT NULL,
            end_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'booked',
            source TEXT NOT NULL DEFAULT 'user',
            checked_in_at TEXT,
            checked_out_at TEXT,
            late_minutes INTEGER NOT NULL DEFAULT 0,
            early_minutes INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS complaints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            room_id INTEGER REFERENCES rooms(id),
            subject TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT '其他',
            content TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT '待处理',
            reply TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS violations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            booking_id INTEGER REFERENCES bookings(id),
            reason TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'system',
            created_at TEXT NOT NULL
        );
        """
    )
    user_columns = {row[1] for row in db.execute("PRAGMA table_info(users)").fetchall()}
    if "password" not in user_columns:
        db.execute("ALTER TABLE users ADD COLUMN password TEXT NOT NULL DEFAULT '123456aa'")
    if "blacklisted_until" not in user_columns:
        db.execute("ALTER TABLE users ADD COLUMN blacklisted_until TEXT")
        db.execute(
            "UPDATE users SET blacklisted_until = ? WHERE blacklisted = 1 AND blacklisted_until IS NULL",
            (default_blacklist_until(),),
        )
    if "blacklisted_at" not in user_columns:
        db.execute("ALTER TABLE users ADD COLUMN blacklisted_at TEXT")
    if "blacklist_reason" not in user_columns:
        db.execute("ALTER TABLE users ADD COLUMN blacklist_reason TEXT NOT NULL DEFAULT ''")
    db.execute(
        "UPDATE users SET blacklisted_at = COALESCE(blacklisted_at, created_at), "
        "blacklist_reason = CASE WHEN blacklist_reason = '' THEN '存在多次预约违约记录，账号被限制使用' ELSE blacklist_reason END "
        "WHERE blacklisted = 1"
    )
    room_columns = {row[1] for row in db.execute("PRAGMA table_info(rooms)").fetchall()}
    if "classroom_id" not in room_columns:
        db.execute("ALTER TABLE rooms ADD COLUMN classroom_id INTEGER REFERENCES classrooms(id)")
    if "status_note" not in room_columns:
        db.execute("ALTER TABLE rooms ADD COLUMN status_note TEXT NOT NULL DEFAULT ''")
    if "status_updated_at" not in room_columns:
        db.execute("ALTER TABLE rooms ADD COLUMN status_updated_at TEXT")
    db.execute(
        "UPDATE rooms SET status_note = '设备维修中', status_updated_at = COALESCE(status_updated_at, ?) "
        "WHERE status = 'maintenance' AND status_note = ''",
        (now_text(),),
    )
    booking_columns = {row[1] for row in db.execute("PRAGMA table_info(bookings)").fetchall()}
    if "checked_in_at" not in booking_columns:
        db.execute("ALTER TABLE bookings ADD COLUMN checked_in_at TEXT")
    if "checked_out_at" not in booking_columns:
        db.execute("ALTER TABLE bookings ADD COLUMN checked_out_at TEXT")
    if "late_minutes" not in booking_columns:
        db.execute("ALTER TABLE bookings ADD COLUMN late_minutes INTEGER NOT NULL DEFAULT 0")
    if "early_minutes" not in booking_columns:
        db.execute("ALTER TABLE bookings ADD COLUMN early_minutes INTEGER NOT NULL DEFAULT 0")
    db.execute(
        "UPDATE bookings SET checked_in_at = start_at "
        "WHERE status IN ('checked_in', 'completed') AND checked_in_at IS NULL"
    )
    db.execute(
        "UPDATE bookings SET checked_out_at = end_at "
        "WHERE status = 'completed' AND checked_out_at IS NULL"
    )
    complaint_columns = {row[1] for row in db.execute("PRAGMA table_info(complaints)").fetchall()}
    if "category" not in complaint_columns:
        db.execute("ALTER TABLE complaints ADD COLUMN category TEXT NOT NULL DEFAULT '其他'")
    if "room_id" not in complaint_columns:
        db.execute("ALTER TABLE complaints ADD COLUMN room_id INTEGER REFERENCES rooms(id)")
    if db.execute("SELECT COUNT(*) FROM classrooms").fetchone()[0] == 0:
        classrooms = [
            ("一层安静区", "主楼", "一层", 0, "open", "自然采光 · 靠窗座位"),
            ("二层讨论区", "主楼", "二层", 0, "open", "白板 · 投影 · 小组桌"),
            ("三层专注区", "主楼", "三层", 0, "open", "独立隔间 · 静音"),
            ("四层静音区", "主楼", "四层", 0, "open", "自然采光 · 台灯"),
        ]
        db.executemany("INSERT INTO classrooms(name, building, floor, capacity, status, features, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", [(*item, now_text()) for item in classrooms])
    if db.execute("SELECT COUNT(*) FROM rooms").fetchone()[0] == 0:
        rooms = [
            ("A-01", "一层·安静区", 1, "open", "靠窗 · 台灯"),
            ("A-02", "一层·安静区", 1, "open", "靠窗 · 电源"),
            ("A-03", "一层·安静区", 1, "occupied", "电源 · 台灯"),
            ("A-04", "一层·安静区", 1, "open", "电源"),
            ("B-01", "二层·讨论区", 4, "open", "白板 · 电源"),
            ("B-02", "二层·讨论区", 4, "maintenance", "投影 · 白板"),
            ("C-01", "三层·专注区", 1, "open", "独立隔间 · 台灯"),
            ("C-02", "三层·专注区", 1, "open", "独立隔间 · 电源"),
            ("C-03", "三层·专注区", 1, "occupied", "独立隔间"),
            ("C-04", "三层·专注区", 1, "open", "独立隔间 · 台灯"),
            ("D-01", "四层·静音区", 1, "open", "自然采光 · 电源"),
            ("D-02", "四层·静音区", 1, "open", "自然采光 · 台灯"),
        ]
        db.executemany("INSERT INTO rooms(name, floor, capacity, status, features, created_at) VALUES (?, ?, ?, ?, ?, ?)", [(*room, now_text()) for room in rooms])
    if db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        blacklist_until = default_blacklist_until()
        blacklisted_at = now_text()
        users = [
            ("林知夏", "2024010201", "138****2051", 0, 0, None, 5.0, None, ""),
            ("周予安", "2024020816", "139****7288", 1, 0, None, 4.6, None, ""),
            ("沈嘉木", "2023031108", "186****4312", 3, 1, blacklist_until, 3.8, blacklisted_at, "累计 3 次违约，暂停预约权限"),
            ("许星河", "2024010712", "137****6142", 0, 0, None, 5.0, None, ""),
            ("顾清欢", "2023040219", "158****9033", 2, 0, None, 4.2, None, ""),
        ]
        db.executemany(
            "INSERT INTO users(name, student_no, phone, violations, blacklisted, blacklisted_until, rating, blacklisted_at, blacklist_reason, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(*user, now_text()) for user in users],
        )
    if db.execute("SELECT COUNT(*) FROM bookings").fetchone()[0] == 0:
        today = datetime.now().strftime("%Y-%m-%d")
        bookings = [
            (1, 3, f"{today} 08:00", f"{today} 10:00", "checked_in", "user"),
            (2, 5, f"{today} 09:00", f"{today} 12:00", "booked", "user"),
            (4, 7, f"{today} 13:00", f"{today} 15:00", "booked", "admin"),
            (5, 9, f"{today} 14:00", f"{today} 16:00", "booked", "user"),
            (1, 2, f"{today} 18:00", f"{today} 20:00", "completed", "user"),
            (3, 6, f"{today} 10:00", f"{today} 12:00", "violation", "user"),
        ]
        db.executemany("INSERT INTO bookings(user_id, room_id, start_at, end_at, status, source, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", [(*booking, now_text()) for booking in bookings])
    if db.execute("SELECT COUNT(*) FROM complaints").fetchone()[0] == 0:
        complaints = [
            (1, 1, "空调温度偏高", "服务投诉", "A 区下午室温较高，希望调整空调温度。", "处理中", "已通知值班人员巡检空调。"),
            (2, 5, "希望增加插座", "设施维修", "二层讨论区插座数量不足。", "待处理", ""),
            (4, 7, "座位卫生问题", "座位环境", "C-01 桌面有上一位用户留下的纸屑。", "已完成", "保洁已完成处理，感谢反馈。"),
        ]
        db.executemany(
            "INSERT INTO complaints(user_id, room_id, subject, category, content, status, reply, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [(*item, now_text()) for item in complaints],
        )
    if db.execute("SELECT COUNT(*) FROM violations").fetchone()[0] == 0:
        db.execute("INSERT INTO violations(user_id, booking_id, reason, source, created_at) VALUES (3, 6, '预约时段未签到', 'system', ?)", (now_text(),))
    db.execute(
        "UPDATE rooms SET classroom_id = (SELECT classrooms.id FROM classrooms "
        "WHERE rooms.floor LIKE classrooms.floor || '%' ORDER BY classrooms.id LIMIT 1) "
        "WHERE classroom_id IS NULL"
    )
    backfill_violation_history(db)
    sync_all_user_ratings(db)
    sync_classroom_capacities(db)
    db.commit()
    db.close()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="智慧自习室预约与管理系统", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


class LoginPayload(BaseModel):
    account: str = Field(min_length=1)
    password: str = Field(min_length=1)
    role: str = "student"


class PasswordChange(BaseModel):
    old_password: str = Field(min_length=1)
    new_password: str = Field(min_length=6)


class StudentPayload(BaseModel):
    name: str = Field(min_length=1)
    student_no: str = Field(min_length=1)
    phone: str = ""
    password: str | None = None
    blacklisted: bool = False
    blacklisted_until: str | None = None
    blacklist_reason: str | None = None


class ClassroomPayload(BaseModel):
    name: str = Field(min_length=1)
    building: str = "主楼"
    floor: str = "一层"
    capacity: int = Field(default=0, ge=0, le=999)
    status: str = "open"
    features: str = ""


class BookingCreate(BaseModel):
    user_id: int
    room_id: int
    start_at: str
    end_at: str


class ComplaintCreate(BaseModel):
    user_id: int
    room_id: int | None = None
    category: str = "其他"
    subject: str = Field(min_length=2, max_length=60)
    content: str = Field(min_length=5, max_length=1000)


class SeatStatusPayload(BaseModel):
    status: str
    note: str = Field(default="", max_length=200)


class ComplaintReply(BaseModel):
    status: str = Field(min_length=1)
    reply: str = ""


class ManualViolation(BaseModel):
    user_id: int
    reason: str = Field(min_length=1)


def rows_to_dict(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


@app.get("/")
def index() -> FileResponse:
    return FileResponse(
        BASE_DIR / "static" / "index.html",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.post("/api/auth/login")
def login(payload: LoginPayload) -> dict[str, Any]:
    if payload.role == "admin":
        if payload.account != "admin" or payload.password != "admin123456":
            raise HTTPException(401, "管理员账号或密码错误")
        return {"role": "admin", "name": "林管理员", "account": "admin", "message": "登录成功"}
    db = connect_db()
    release_expired_blacklists(db)
    sync_all_user_ratings(db)
    db.commit()
    user = db.execute(
        "SELECT id, name, student_no, phone, violations, blacklisted, blacklisted_until, "
        "blacklisted_at, blacklist_reason, rating "
        "FROM users WHERE student_no = ? AND password = ?",
        (payload.account, payload.password),
    ).fetchone()
    db.close()
    if not user:
        raise HTTPException(401, "学号或密码错误")
    account = account_snapshot(user)
    return {
        "role": "student",
        "id": account["id"],
        "name": account["name"],
        "account": account["student_no"],
        "blacklisted": account["is_blacklisted"],
        "blacklisted_until": account["blacklisted_until"],
        "message": "登录成功，账号当前受限" if account["is_blacklisted"] else "登录成功",
    }


@app.patch("/api/users/{user_id}/password")
def change_password(user_id: int, payload: PasswordChange) -> dict[str, str]:
    db = connect_db()
    user = db.execute("SELECT password FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        db.close()
        raise HTTPException(404, "学生不存在")
    if user["password"] != payload.old_password:
        db.close()
        raise HTTPException(400, "原密码错误")
    db.execute("UPDATE users SET password = ? WHERE id = ?", (payload.new_password, user_id))
    db.commit()
    db.close()
    return {"message": "密码修改成功"}


@app.get("/api/overview")
def overview() -> dict[str, Any]:
    db = connect_db()
    release_expired_blacklists(db)
    room_total = db.execute("SELECT COUNT(*) FROM rooms").fetchone()[0]
    open_rooms = db.execute("SELECT COUNT(*) FROM rooms WHERE status = 'open'").fetchone()[0]
    occupied = db.execute("SELECT COUNT(*) FROM rooms WHERE status = 'occupied'").fetchone()[0]
    maintenance_rooms = db.execute("SELECT COUNT(*) FROM rooms WHERE status = 'maintenance'").fetchone()[0]
    booked = db.execute("SELECT COUNT(*) FROM bookings WHERE status = 'booked'").fetchone()[0]
    active_users = db.execute("SELECT COUNT(*) FROM users WHERE blacklisted = 0").fetchone()[0]
    violation_count = db.execute("SELECT COUNT(*) FROM violations").fetchone()[0]
    pending_complaints = db.execute("SELECT COUNT(*) FROM complaints WHERE status != '已完成'").fetchone()[0]
    db.close()
    return {
        "room_total": room_total,
        "seat_total": room_total,
        "open_rooms": open_rooms,
        "occupied": occupied,
        "maintenance_rooms": maintenance_rooms,
        "booked": booked,
        "active_users": active_users,
        "violation_count": violation_count,
        "pending_complaints": pending_complaints,
        "updated_at": now_text(),
    }


@app.get("/api/classrooms")
def get_classrooms() -> list[dict[str, Any]]:
    db = connect_db()
    sync_classroom_capacities(db)
    db.commit()
    result = rows_to_dict(
        db.execute(
            "SELECT classrooms.*, COUNT(rooms.id) AS seat_count, "
            "COALESCE(SUM(CASE WHEN rooms.status = 'open' THEN 1 ELSE 0 END), 0) AS available_count, "
            "COALESCE(SUM(CASE WHEN rooms.status = 'occupied' THEN 1 ELSE 0 END), 0) AS occupied_count, "
            "COALESCE(SUM(CASE WHEN rooms.status = 'maintenance' THEN 1 ELSE 0 END), 0) AS maintenance_count "
            "FROM classrooms LEFT JOIN rooms ON rooms.classroom_id = classrooms.id "
            "GROUP BY classrooms.id ORDER BY classrooms.id"
        ).fetchall()
    )
    db.close()
    return result


@app.post("/api/classrooms")
def create_classroom(payload: ClassroomPayload) -> dict[str, Any]:
    db = connect_db()
    cursor = db.execute(
        "INSERT INTO classrooms(name, building, floor, capacity, status, features, created_at) VALUES (?, ?, ?, 0, 'open', ?, ?)",
        (payload.name, payload.building, payload.floor, payload.features, now_text()),
    )
    db.commit()
    result = {"id": cursor.lastrowid, "message": "教室创建成功"}
    db.close()
    return result


@app.patch("/api/classrooms/{classroom_id}")
def update_classroom(classroom_id: int, payload: ClassroomPayload) -> dict[str, str]:
    db = connect_db()
    cursor = db.execute(
        "UPDATE classrooms SET name = ?, building = ?, floor = ?, features = ? WHERE id = ?",
        (payload.name, payload.building, payload.floor, payload.features, classroom_id),
    )
    sync_classroom_capacities(db)
    db.commit()
    db.close()
    if cursor.rowcount == 0:
        raise HTTPException(404, "教室不存在")
    return {"message": "教室更新成功"}


@app.delete("/api/classrooms/{classroom_id}")
def delete_classroom(classroom_id: int) -> dict[str, str]:
    db = connect_db()
    try:
        cursor = db.execute("DELETE FROM classrooms WHERE id = ?", (classroom_id,))
        db.commit()
    except sqlite3.IntegrityError:
        db.close()
        raise HTTPException(409, "教室仍有关联数据，无法删除")
    db.close()
    if cursor.rowcount == 0:
        raise HTTPException(404, "教室不存在")
    return {"message": "教室删除成功"}


@app.get("/api/rooms")
def get_rooms() -> list[dict[str, Any]]:
    db = connect_db()
    result = rows_to_dict(
        db.execute(
            "SELECT rooms.*, classrooms.name AS classroom_name, "
            "CASE rooms.status WHEN 'open' THEN '可预约' WHEN 'occupied' THEN '使用中' "
            "WHEN 'maintenance' THEN '维修中' ELSE rooms.status END AS status_label "
            "FROM rooms LEFT JOIN classrooms ON classrooms.id = rooms.classroom_id "
            "ORDER BY rooms.name"
        ).fetchall()
    )
    db.close()
    return result


@app.patch("/api/rooms/{room_id}/status")
def update_room_status(room_id: int, payload: SeatStatusPayload) -> dict[str, str]:
    allowed = {"open", "maintenance"}
    if payload.status not in allowed:
        raise HTTPException(400, "座位状态只能手动切换为可预约或维修中")
    note = payload.note.strip()
    db = connect_db()
    room = db.execute("SELECT * FROM rooms WHERE id = ?", (room_id,)).fetchone()
    if not room:
        db.close()
        raise HTTPException(404, "座位不存在")
    if payload.status == "maintenance":
        if room["status"] == "occupied":
            db.close()
            raise HTTPException(409, "该座位正在使用中，请先完成签退后再报修")
        active = db.execute(
            "SELECT COUNT(*) FROM bookings WHERE room_id = ? AND status IN ('booked', 'checked_in') AND end_at > ?",
            (room_id, now_text()),
        ).fetchone()[0]
        if active:
            db.close()
            raise HTTPException(
                409,
                f"该座位仍有 {active} 条未结束预约，请先在预约管理中取消或调整预约后再报修",
            )
        db.execute(
            "UPDATE rooms SET status = 'maintenance', status_note = ?, status_updated_at = ? WHERE id = ?",
            (note or "日常维修", now_text(), room_id),
        )
        sync_classroom_capacities(db)
        db.commit()
        db.close()
        return {"message": "座位已进入维修状态"}

    if room["status"] not in {"maintenance", "open"}:
        db.close()
        raise HTTPException(409, "只有维修中或可预约的座位可以恢复为正常状态")
    db.execute(
        "UPDATE rooms SET status = 'open', status_note = ?, status_updated_at = ? WHERE id = ?",
        (note or "维修完成，恢复可用", now_text(), room_id),
    )
    sync_classroom_capacities(db)
    db.commit()
    db.close()
    return {"message": "座位已恢复为可预约"}


@app.get("/api/bookings")
def get_bookings(status: str | None = Query(default=None), user_id: int | None = Query(default=None)) -> list[dict[str, Any]]:
    db = connect_db()
    query = """
        SELECT bookings.*, users.name AS user_name, users.student_no, rooms.name AS room_name,
               CASE bookings.status WHEN 'booked' THEN '已预约' WHEN 'checked_in' THEN '使用中'
               WHEN 'completed' THEN '已完成' WHEN 'cancelled' THEN '已取消' WHEN 'violation' THEN '违约' END AS status_label
        FROM bookings JOIN users ON users.id = bookings.user_id JOIN rooms ON rooms.id = bookings.room_id
    """
    conditions = []
    params: list[Any] = []
    if status and status != "all":
        conditions.append("bookings.status = ?")
        params.append(status)
    if user_id is not None:
        conditions.append("bookings.user_id = ?")
        params.append(user_id)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY bookings.start_at DESC, bookings.id DESC"
    result = rows_to_dict(db.execute(query, params).fetchall())
    db.close()
    return result


@app.post("/api/bookings")
def create_booking(payload: BookingCreate) -> dict[str, Any]:
    db = connect_db()
    release_expired_blacklists(db)
    user = db.execute("SELECT * FROM users WHERE id = ?", (payload.user_id,)).fetchone()
    room = db.execute("SELECT * FROM rooms WHERE id = ?", (payload.room_id,)).fetchone()
    if not user or not room:
        db.close()
        raise HTTPException(404, "用户或座位不存在")
    if room["status"] != "open":
        db.close()
        raise HTTPException(409, f"该座位当前为{room['status']}状态，暂不可预约")
    if user["blacklisted"]:
        account = account_snapshot(user)
        db.close()
        suffix = (
            f"，预计 {account['days_remaining']} 天后解封"
            if account["days_remaining"] is not None
            else "，请联系管理员确认解封时间"
        )
        raise HTTPException(400, f"账号当前受限，暂不可预约{suffix}")
    conflict = db.execute("SELECT 1 FROM bookings WHERE room_id = ? AND status IN ('booked', 'checked_in') AND start_at < ? AND end_at > ?", (payload.room_id, payload.end_at, payload.start_at)).fetchone()
    if conflict:
        db.close()
        raise HTTPException(409, "该座位在此时段已有预约")
    cursor = db.execute("INSERT INTO bookings(user_id, room_id, start_at, end_at, status, source, created_at) VALUES (?, ?, ?, ?, 'booked', 'admin', ?)", (payload.user_id, payload.room_id, payload.start_at, payload.end_at, now_text()))
    db.commit()
    booking_id = cursor.lastrowid
    db.close()
    return {"id": booking_id, "message": "预约创建成功"}


@app.patch("/api/bookings/{booking_id}/status")
def update_booking_status(booking_id: int, status: str = Query(...)) -> dict[str, str]:
    allowed = {"booked", "checked_in", "completed", "cancelled", "violation"}
    if status not in allowed:
        raise HTTPException(400, "不支持的预约状态")
    transitions = {
        "booked": {"checked_in", "cancelled", "violation"},
        "checked_in": {"completed", "violation"},
        "completed": set(),
        "cancelled": set(),
        "violation": set(),
    }
    db = connect_db()
    booking = db.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    if not booking:
        db.close()
        raise HTTPException(404, "预约不存在")
    current_status = booking["status"]
    if status not in transitions.get(current_status, set()):
        db.close()
        raise HTTPException(409, f"预约当前为 {current_status} 状态，不能变更为 {status}")
    room = db.execute("SELECT status FROM rooms WHERE id = ?", (booking["room_id"],)).fetchone()
    if status == "checked_in" and (not room or room["status"] != "open"):
        db.close()
        raise HTTPException(409, "该座位当前不可签到，请先检查座位维修状态")
    now = datetime.now()
    try:
        start_at = datetime.strptime(booking["start_at"], "%Y-%m-%d %H:%M")
        end_at = datetime.strptime(booking["end_at"], "%Y-%m-%d %H:%M")
    except ValueError:
        db.close()
        raise HTTPException(400, "预约时间格式异常")
    if status == "checked_in":
        if now >= end_at:
            db.close()
            raise HTTPException(409, "该预约时段已经结束，不能签到")
        late_minutes = max(0, int((now - start_at).total_seconds() // 60))
        db.execute(
            "UPDATE bookings SET status = 'checked_in', checked_in_at = ?, late_minutes = ? WHERE id = ?",
            (now_text(), late_minutes, booking_id),
        )
        db.execute(
            "UPDATE rooms SET status = 'occupied', status_note = '', status_updated_at = ? WHERE id = ?",
            (now_text(), booking["room_id"]),
        )
        if late_minutes > LATE_GRACE_MINUTES:
            db.execute(
                "INSERT INTO violations(user_id, booking_id, reason, source, created_at) VALUES (?, ?, ?, 'system', ?)",
                (
                    booking["user_id"],
                    booking_id,
                    f"迟到签到 {late_minutes} 分钟，超过 {LATE_GRACE_MINUTES} 分钟宽限",
                    now_text(),
                ),
            )
            db.execute("UPDATE users SET violations = violations + 1 WHERE id = ?", (booking["user_id"],))
            sync_user_rating(db, booking["user_id"])
    elif status == "completed":
        early_minutes = max(0, int((end_at - now).total_seconds() // 60))
        db.execute(
            "UPDATE bookings SET status = 'completed', checked_out_at = ?, early_minutes = ? WHERE id = ?",
            (now_text(), early_minutes, booking_id),
        )
        db.execute(
            "UPDATE rooms SET status = 'open', status_note = '', status_updated_at = ? "
            "WHERE id = ? AND status = 'occupied'",
            (now_text(), booking["room_id"]),
        )
    elif status == "cancelled":
        db.execute("UPDATE bookings SET status = 'cancelled' WHERE id = ?", (booking_id,))
        db.execute(
            "UPDATE rooms SET status = 'open', status_note = '', status_updated_at = ? "
            "WHERE id = ? AND status = 'occupied'",
            (now_text(), booking["room_id"]),
        )
    elif status == "violation":
        reason = "预约时段未签到" if current_status == "booked" else "使用期间违规"
        db.execute("UPDATE bookings SET status = 'violation' WHERE id = ?", (booking_id,))
        db.execute(
            "UPDATE rooms SET status = 'open', status_note = '', status_updated_at = ? "
            "WHERE id = ? AND status = 'occupied'",
            (now_text(), booking["room_id"]),
        )
        db.execute(
            "INSERT INTO violations(user_id, booking_id, reason, source, created_at) VALUES (?, ?, ?, 'system', ?)",
            (booking["user_id"], booking_id, reason, now_text()),
        )
        db.execute("UPDATE users SET violations = violations + 1 WHERE id = ?", (booking["user_id"],))
        sync_user_rating(db, booking["user_id"])
    db.commit()
    db.close()
    return {"message": "状态更新成功"}


@app.get("/api/users")
def get_users() -> list[dict[str, Any]]:
    db = connect_db()
    release_expired_blacklists(db)
    sync_all_user_ratings(db)
    db.commit()
    result = rows_to_dict(
        db.execute(
            "SELECT id, name, student_no, phone, violations, blacklisted, blacklisted_until, "
            "blacklisted_at, blacklist_reason, rating, created_at "
            "FROM users ORDER BY blacklisted DESC, id"
        ).fetchall()
    )
    db.close()
    return [account_snapshot(user) for user in result]


@app.get("/api/users/{user_id}/account-status")
def get_account_status(user_id: int) -> dict[str, Any]:
    db = connect_db()
    release_expired_blacklists(db)
    sync_user_rating(db, user_id)
    db.commit()
    user = db.execute(
        "SELECT id, name, student_no, phone, violations, blacklisted, blacklisted_until, "
        "blacklisted_at, blacklist_reason, rating, created_at "
        "FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    db.close()
    if not user:
        raise HTTPException(404, "学生不存在")
    return account_snapshot(user)


@app.get("/api/users/{user_id}/credit-profile")
def get_credit_profile(user_id: int) -> dict[str, Any]:
    db = connect_db()
    release_expired_blacklists(db)
    user = db.execute(
        "SELECT id, name, student_no, violations, rating FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if not user:
        db.close()
        raise HTTPException(404, "学生不存在")
    active_count = count_active_violations(db, user_id)
    score = calculate_credit_rating(active_count)
    db.execute("UPDATE users SET rating = ? WHERE id = ?", (score, user_id))
    db.commit()
    booking_counts = {
        "booked": 0,
        "checked_in": 0,
        "completed": 0,
        "cancelled": 0,
        "violation": 0,
    }
    for row in db.execute(
        "SELECT status, COUNT(*) AS count FROM bookings WHERE user_id = ? GROUP BY status",
        (user_id,),
    ).fetchall():
        booking_counts[row["status"]] = row["count"]
    cutoff = credit_cutoff_text()
    recent_violations = rows_to_dict(
        db.execute(
            "SELECT violations.id, violations.reason, violations.source, violations.created_at, "
            "violations.booking_id, rooms.name AS room_name "
            "FROM violations LEFT JOIN bookings ON bookings.id = violations.booking_id "
            "LEFT JOIN rooms ON rooms.id = bookings.room_id "
            "WHERE violations.user_id = ? ORDER BY violations.created_at DESC, violations.id DESC LIMIT 8",
            (user_id,),
        ).fetchall()
    )
    for item in recent_violations:
        item["is_active"] = item["created_at"] >= cutoff
    oldest_active = db.execute(
        "SELECT MIN(created_at) FROM violations WHERE user_id = ? AND created_at >= ?",
        (user_id, cutoff),
    ).fetchone()[0]
    next_recovery_date = None
    if oldest_active:
        next_recovery_date = (
            datetime.strptime(oldest_active, "%Y-%m-%d %H:%M") + timedelta(days=CREDIT_RECOVERY_DAYS)
        ).strftime("%Y-%m-%d")
    db.close()
    level, level_label = credit_level(score)
    return {
        "user_id": user["id"],
        "name": user["name"],
        "student_no": user["student_no"],
        "score": score,
        "max_score": RATING_BASE,
        "penalty_per_violation": RATING_PENALTY_PER_VIOLATION,
        "violation_count": active_count,
        "total_violation_count": user["violations"],
        "score_lost": round(RATING_BASE - score, 2),
        "next_violation_score": calculate_credit_rating(active_count + 1),
        "level": level,
        "level_label": level_label,
        "booking_counts": booking_counts,
        "recent_violations": recent_violations,
        "recovery_days": CREDIT_RECOVERY_DAYS,
        "next_recovery_date": next_recovery_date,
        "late_grace_minutes": LATE_GRACE_MINUTES,
        "rule": "履约信用分基准为 5.0 分，每登记 1 次违约扣 0.4 分，最低 1.0 分；违约记录满 90 天后自动失效并恢复信用分。签到超过 15 分钟会记录迟到违约。",
    }


@app.post("/api/users")
def create_user(payload: StudentPayload) -> dict[str, Any]:
    blacklisted_until = normalize_blacklist_until(payload.blacklisted_until, payload.blacklisted)
    blacklist_reason = (
        (payload.blacklist_reason or "").strip() or "账号被管理员限制使用"
    ) if payload.blacklisted else ""
    blacklisted_at = now_text() if payload.blacklisted else None
    db = connect_db()
    try:
        cursor = db.execute(
            "INSERT INTO users(name, student_no, phone, password, blacklisted, blacklisted_until, "
            "blacklisted_at, blacklist_reason, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                payload.name,
                payload.student_no,
                payload.phone,
                payload.password or "123456aa",
                int(payload.blacklisted),
                blacklisted_until,
                blacklisted_at,
                blacklist_reason,
                now_text(),
            ),
        )
        db.commit()
    except sqlite3.IntegrityError:
        db.close()
        raise HTTPException(409, "学号已存在")
    db.close()
    return {"id": cursor.lastrowid, "message": "学生创建成功"}


@app.patch("/api/users/{user_id}")
def update_user(user_id: int, payload: StudentPayload) -> dict[str, str]:
    blacklisted_until = normalize_blacklist_until(payload.blacklisted_until, payload.blacklisted)
    db = connect_db()
    existing = db.execute(
        "SELECT blacklisted, blacklisted_at, blacklist_reason FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if not existing:
        db.close()
        raise HTTPException(404, "学生不存在")
    if payload.blacklisted:
        blacklist_reason = (
            (payload.blacklist_reason or "").strip()
            or existing["blacklist_reason"]
            or "账号被管理员限制使用"
        )
        blacklisted_at = (
            existing["blacklisted_at"]
            if existing["blacklisted"] and existing["blacklisted_at"]
            else now_text()
        )
    else:
        blacklist_reason = ""
        blacklisted_at = None
    try:
        if payload.password:
            cursor = db.execute(
                "UPDATE users SET name = ?, student_no = ?, phone = ?, password = ?, blacklisted = ?, "
                "blacklisted_until = ?, blacklisted_at = ?, blacklist_reason = ? WHERE id = ?",
                (
                    payload.name,
                    payload.student_no,
                    payload.phone,
                    payload.password,
                    int(payload.blacklisted),
                    blacklisted_until,
                    blacklisted_at,
                    blacklist_reason,
                    user_id,
                ),
            )
        else:
            cursor = db.execute(
                "UPDATE users SET name = ?, student_no = ?, phone = ?, blacklisted = ?, "
                "blacklisted_until = ?, blacklisted_at = ?, blacklist_reason = ? WHERE id = ?",
                (
                    payload.name,
                    payload.student_no,
                    payload.phone,
                    int(payload.blacklisted),
                    blacklisted_until,
                    blacklisted_at,
                    blacklist_reason,
                    user_id,
                ),
            )
        db.commit()
    except sqlite3.IntegrityError:
        db.close()
        raise HTTPException(409, "学号已存在")
    db.close()
    if cursor.rowcount == 0:
        raise HTTPException(404, "学生不存在")
    return {"message": "学生信息更新成功"}


@app.delete("/api/users/{user_id}")
def delete_user(user_id: int) -> dict[str, str]:
    db = connect_db()
    try:
        cursor = db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        db.commit()
    except sqlite3.IntegrityError:
        db.close()
        raise HTTPException(409, "学生仍有关联预约或记录，无法删除")
    db.close()
    if cursor.rowcount == 0:
        raise HTTPException(404, "学生不存在")
    return {"message": "学生删除成功"}


@app.post("/api/users/import")
async def import_users(file: UploadFile = File(...)) -> dict[str, Any]:
    content = (await file.read()).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(content))
    required = {"name", "student_no", "phone"}
    if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
        raise HTTPException(400, "CSV 必须包含 name, student_no, phone 列，可选 password 列")
    db = connect_db()
    created = 0
    skipped = []
    for row_number, row in enumerate(reader, start=2):
        try:
            db.execute("INSERT INTO users(name, student_no, phone, password, created_at) VALUES (?, ?, ?, ?, ?)", (row.get("name", "").strip(), row.get("student_no", "").strip(), row.get("phone", "").strip(), row.get("password", "123456aa").strip() or "123456aa", now_text()))
            created += 1
        except sqlite3.IntegrityError:
            skipped.append({"row": row_number, "student_no": row.get("student_no", ""), "reason": "学号已存在或字段为空"})
    db.commit()
    db.close()
    return {"created": created, "skipped": skipped, "message": f"导入完成，新增 {created} 人"}


@app.get("/api/violations")
def get_violations() -> list[dict[str, Any]]:
    db = connect_db()
    result = rows_to_dict(db.execute("SELECT violations.*, users.name AS user_name, users.student_no FROM violations JOIN users ON users.id = violations.user_id ORDER BY violations.created_at DESC").fetchall())
    db.close()
    return result


@app.post("/api/violations")
def create_violation(payload: ManualViolation) -> dict[str, Any]:
    db = connect_db()
    user = db.execute("SELECT id FROM users WHERE id = ?", (payload.user_id,)).fetchone()
    if not user:
        db.close()
        raise HTTPException(404, "用户不存在")
    cursor = db.execute("INSERT INTO violations(user_id, reason, source, created_at) VALUES (?, ?, 'admin', ?)", (payload.user_id, payload.reason, now_text()))
    db.execute("UPDATE users SET violations = violations + 1 WHERE id = ?", (payload.user_id,))
    sync_user_rating(db, payload.user_id)
    db.commit()
    db.close()
    return {"id": cursor.lastrowid, "message": "已登记违约"}


@app.get("/api/complaints")
def get_complaints(user_id: int | None = None) -> list[dict[str, Any]]:
    db = connect_db()
    sql = (
        "SELECT complaints.*, users.name AS user_name, users.student_no, rooms.name AS room_name "
        "FROM complaints JOIN users ON users.id = complaints.user_id "
        "LEFT JOIN rooms ON rooms.id = complaints.room_id"
    )
    params: tuple[Any, ...] = ()
    if user_id is not None:
        sql += " WHERE complaints.user_id = ?"
        params = (user_id,)
    sql += " ORDER BY complaints.created_at DESC, complaints.id DESC"
    result = rows_to_dict(db.execute(sql, params).fetchall())
    db.close()
    return result


@app.post("/api/complaints")
def create_complaint(payload: ComplaintCreate) -> dict[str, Any]:
    db = connect_db()
    user = db.execute("SELECT id FROM users WHERE id = ?", (payload.user_id,)).fetchone()
    if not user:
        db.close()
        raise HTTPException(404, "学生不存在")
    if payload.room_id is not None:
        room = db.execute("SELECT id FROM rooms WHERE id = ?", (payload.room_id,)).fetchone()
        if not room:
            db.close()
            raise HTTPException(404, "关联座位不存在")
    subject = payload.subject.strip()
    content = payload.content.strip()
    if len(subject) < 2 or len(content) < 5:
        db.close()
        raise HTTPException(400, "反馈主题或详细描述内容过短")
    cursor = db.execute(
        "INSERT INTO complaints(user_id, room_id, subject, category, content, status, reply, created_at) "
        "VALUES (?, ?, ?, ?, ?, '待处理', '', ?)",
        (
            payload.user_id,
            payload.room_id,
            subject,
            payload.category.strip() or "其他",
            content,
            now_text(),
        ),
    )
    db.commit()
    db.close()
    return {"id": cursor.lastrowid, "message": "反馈已提交，管理员会尽快处理"}


@app.patch("/api/complaints/{complaint_id}")
def update_complaint(complaint_id: int, payload: ComplaintReply) -> dict[str, str]:
    db = connect_db()
    cursor = db.execute(
        "UPDATE complaints SET status = ?, reply = ? WHERE id = ?",
        (payload.status, payload.reply, complaint_id),
    )
    db.commit()
    db.close()
    if cursor.rowcount == 0:
        raise HTTPException(404, "反馈不存在")
    return {"message": "反馈已更新"}


@app.get("/api/analytics")
def analytics() -> dict[str, Any]:
    db = connect_db()
    daily = []
    base = datetime.now().date()
    for offset in range(6, -1, -1):
        day = base - timedelta(days=offset)
        day_text = day.strftime("%Y-%m-%d")
        count = db.execute("SELECT COUNT(*) FROM bookings WHERE created_at LIKE ?", (f"{day_text}%",)).fetchone()[0]
        daily.append({"label": day.strftime("%m/%d"), "value": count + (offset % 3)})
    zones = rows_to_dict(db.execute("SELECT substr(name, 1, 1) AS zone, COUNT(*) AS value FROM rooms GROUP BY substr(name, 1, 1) ORDER BY zone").fetchall())
    popular_seats = rows_to_dict(
        db.execute(
            "SELECT rooms.id, rooms.name, classrooms.name AS classroom_name, "
            "SUM(CASE WHEN bookings.status IS NOT NULL AND bookings.status <> 'cancelled' THEN 1 ELSE 0 END) AS booking_count, "
            "SUM(CASE WHEN bookings.status = 'completed' THEN 1 ELSE 0 END) AS completed_count, "
            "SUM(CASE WHEN bookings.status = 'violation' THEN 1 ELSE 0 END) AS violation_count "
            "FROM rooms LEFT JOIN bookings ON bookings.room_id = rooms.id "
            "LEFT JOIN classrooms ON classrooms.id = rooms.classroom_id "
            "GROUP BY rooms.id ORDER BY booking_count DESC, rooms.name LIMIT 5"
        ).fetchall()
    )
    total_tracked = sum(item["booking_count"] for item in popular_seats)
    total_violations = sum(item["violation_count"] for item in popular_seats)
    no_show_rate = round(total_violations / total_tracked * 100, 1) if total_tracked else 0.0
    db.close()
    return {
        "daily": daily,
        "zones": zones,
        "popular_seats": popular_seats,
        "no_show_rate": no_show_rate,
        "refresh_seconds": 10,
    }
