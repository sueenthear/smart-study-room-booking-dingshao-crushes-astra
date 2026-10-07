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


def init_db() -> None:
    db = connect_db()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS rooms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            floor TEXT NOT NULL,
            capacity INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'open',
            features TEXT NOT NULL DEFAULT '',
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
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS complaints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            subject TEXT NOT NULL,
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
    if db.execute("SELECT COUNT(*) FROM classrooms").fetchone()[0] == 0:
        classrooms = [
            ("一层安静区", "主楼", "一层", 24, "open", "自然采光 · 靠窗座位"),
            ("二层讨论区", "主楼", "二层", 32, "open", "白板 · 投影 · 小组桌"),
            ("三层专注区", "主楼", "三层", 28, "open", "独立隔间 · 静音"),
            ("四层静音区", "主楼", "四层", 20, "maintenance", "自然采光 · 台灯"),
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
        users = [
            ("林知夏", "2024010201", "138****2051", 0, 0, 4.9),
            ("周予安", "2024020816", "139****7288", 1, 0, 4.6),
            ("沈嘉木", "2023031108", "186****4312", 3, 1, 3.8),
            ("许星河", "2024010712", "137****6142", 0, 0, 5.0),
            ("顾清欢", "2023040219", "158****9033", 2, 0, 4.2),
        ]
        db.executemany("INSERT INTO users(name, student_no, phone, violations, blacklisted, rating, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", [(*user, now_text()) for user in users])
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
            (1, "空调温度偏高", "A 区下午室温较高，希望调整空调温度。", "处理中", "已通知值班人员巡检空调。"),
            (2, "希望增加插座", "二层讨论区插座数量不足。", "待处理", ""),
            (4, "座位卫生问题", "C-01 桌面有上一位用户留下的纸屑。", "已完成", "保洁已完成处理，感谢反馈。"),
        ]
        db.executemany("INSERT INTO complaints(user_id, subject, content, status, reply, created_at) VALUES (?, ?, ?, ?, ?, ?)", [(*item, now_text()) for item in complaints])
    if db.execute("SELECT COUNT(*) FROM violations").fetchone()[0] == 0:
        db.execute("INSERT INTO violations(user_id, booking_id, reason, source, created_at) VALUES (3, 6, '预约时段未签到', 'system', ?)", (now_text(),))
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


class ClassroomPayload(BaseModel):
    name: str = Field(min_length=1)
    building: str = "主楼"
    floor: str = "一层"
    capacity: int = Field(default=1, ge=1, le=999)
    status: str = "open"
    features: str = ""


class BookingCreate(BaseModel):
    user_id: int
    room_id: int
    start_at: str
    end_at: str


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
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.post("/api/auth/login")
def login(payload: LoginPayload) -> dict[str, Any]:
    if payload.role == "admin":
        if payload.account != "admin" or payload.password != "admin123456":
            raise HTTPException(401, "管理员账号或密码错误")
        return {"role": "admin", "name": "林管理员", "account": "admin", "message": "登录成功"}
    db = connect_db()
    user = db.execute("SELECT id, name, student_no, blacklisted FROM users WHERE student_no = ? AND password = ?", (payload.account, payload.password)).fetchone()
    db.close()
    if not user:
        raise HTTPException(401, "学号或密码错误")
    if user["blacklisted"]:
        raise HTTPException(403, "该账号已进入黑名单，请联系管理员")
    return {"role": "student", "id": user["id"], "name": user["name"], "account": user["student_no"], "message": "登录成功"}


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
    room_total = db.execute("SELECT COUNT(*) FROM rooms").fetchone()[0]
    open_rooms = db.execute("SELECT COUNT(*) FROM rooms WHERE status = 'open'").fetchone()[0]
    occupied = db.execute("SELECT COUNT(*) FROM rooms WHERE status = 'occupied'").fetchone()[0]
    booked = db.execute("SELECT COUNT(*) FROM bookings WHERE status = 'booked'").fetchone()[0]
    active_users = db.execute("SELECT COUNT(*) FROM users WHERE blacklisted = 0").fetchone()[0]
    violation_count = db.execute("SELECT COUNT(*) FROM violations").fetchone()[0]
    pending_complaints = db.execute("SELECT COUNT(*) FROM complaints WHERE status != '已完成'").fetchone()[0]
    db.close()
    return {"room_total": room_total, "open_rooms": open_rooms, "occupied": occupied, "booked": booked, "active_users": active_users, "violation_count": violation_count, "pending_complaints": pending_complaints, "updated_at": now_text()}


@app.get("/api/classrooms")
def get_classrooms() -> list[dict[str, Any]]:
    db = connect_db()
    result = rows_to_dict(db.execute("SELECT * FROM classrooms ORDER BY id").fetchall())
    db.close()
    return result


@app.post("/api/classrooms")
def create_classroom(payload: ClassroomPayload) -> dict[str, Any]:
    db = connect_db()
    cursor = db.execute("INSERT INTO classrooms(name, building, floor, capacity, status, features, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (payload.name, payload.building, payload.floor, payload.capacity, payload.status, payload.features, now_text()))
    db.commit()
    result = {"id": cursor.lastrowid, "message": "教室创建成功"}
    db.close()
    return result


@app.patch("/api/classrooms/{classroom_id}")
def update_classroom(classroom_id: int, payload: ClassroomPayload) -> dict[str, str]:
    db = connect_db()
    cursor = db.execute("UPDATE classrooms SET name = ?, building = ?, floor = ?, capacity = ?, status = ?, features = ? WHERE id = ?", (payload.name, payload.building, payload.floor, payload.capacity, payload.status, payload.features, classroom_id))
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
    result = rows_to_dict(db.execute("SELECT * FROM rooms ORDER BY name").fetchall())
    db.close()
    return result


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
    user = db.execute("SELECT * FROM users WHERE id = ?", (payload.user_id,)).fetchone()
    room = db.execute("SELECT * FROM rooms WHERE id = ?", (payload.room_id,)).fetchone()
    if not user or not room:
        db.close()
        raise HTTPException(404, "用户或座位不存在")
    if user["blacklisted"]:
        db.close()
        raise HTTPException(400, "黑名单用户不可预约")
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
    db = connect_db()
    booking = db.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    if not booking:
        db.close()
        raise HTTPException(404, "预约不存在")
    db.execute("UPDATE bookings SET status = ? WHERE id = ?", (status, booking_id))
    if status == "checked_in":
        db.execute("UPDATE rooms SET status = 'occupied' WHERE id = ?", (booking["room_id"],))
    elif status in {"completed", "cancelled", "violation"}:
        db.execute("UPDATE rooms SET status = 'open' WHERE id = ? AND status = 'occupied'", (booking["room_id"],))
    if status == "violation":
        db.execute("INSERT INTO violations(user_id, booking_id, reason, source, created_at) VALUES (?, ?, '预约时段未签到', 'system', ?)", (booking["user_id"], booking_id, now_text()))
        db.execute("UPDATE users SET violations = violations + 1 WHERE id = ?", (booking["user_id"],))
    db.commit()
    db.close()
    return {"message": "状态更新成功"}


@app.get("/api/users")
def get_users() -> list[dict[str, Any]]:
    db = connect_db()
    result = rows_to_dict(db.execute("SELECT id, name, student_no, phone, violations, blacklisted, rating, created_at FROM users ORDER BY blacklisted DESC, id").fetchall())
    db.close()
    return result


@app.post("/api/users")
def create_user(payload: StudentPayload) -> dict[str, Any]:
    db = connect_db()
    try:
        cursor = db.execute("INSERT INTO users(name, student_no, phone, password, blacklisted, created_at) VALUES (?, ?, ?, ?, ?, ?)", (payload.name, payload.student_no, payload.phone, payload.password or "123456aa", int(payload.blacklisted), now_text()))
        db.commit()
    except sqlite3.IntegrityError:
        db.close()
        raise HTTPException(409, "学号已存在")
    db.close()
    return {"id": cursor.lastrowid, "message": "学生创建成功"}


@app.patch("/api/users/{user_id}")
def update_user(user_id: int, payload: StudentPayload) -> dict[str, str]:
    db = connect_db()
    try:
        if payload.password:
            cursor = db.execute("UPDATE users SET name = ?, student_no = ?, phone = ?, password = ?, blacklisted = ? WHERE id = ?", (payload.name, payload.student_no, payload.phone, payload.password, int(payload.blacklisted), user_id))
        else:
            cursor = db.execute("UPDATE users SET name = ?, student_no = ?, phone = ?, blacklisted = ? WHERE id = ?", (payload.name, payload.student_no, payload.phone, int(payload.blacklisted), user_id))
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
    db.commit()
    db.close()
    return {"id": cursor.lastrowid, "message": "已登记违约"}


@app.get("/api/complaints")
def get_complaints() -> list[dict[str, Any]]:
    db = connect_db()
    result = rows_to_dict(db.execute("SELECT complaints.*, users.name AS user_name FROM complaints JOIN users ON users.id = complaints.user_id ORDER BY complaints.created_at DESC").fetchall())
    db.close()
    return result


@app.patch("/api/complaints/{complaint_id}")
def update_complaint(complaint_id: int, payload: ComplaintReply) -> dict[str, str]:
    db = connect_db()
    db.execute("UPDATE complaints SET status = ?, reply = ? WHERE id = ?", (payload.status, payload.reply, complaint_id))
    db.commit()
    db.close()
    return {"message": "投诉反馈已更新"}


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
    db.close()
    return {"daily": daily, "zones": zones, "refresh_seconds": 10}
