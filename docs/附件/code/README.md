# 代码快照与运行说明

`03` 的 B.2（AI-01 规格落地核对、AI-03 证据核对）需要说明"核的是哪一版代码"。光写"我看了代码"不算证据，要能给出版本标识与启动方式。

## 需要补的两件

1. **版本标识**：在项目根执行 `git rev-parse --short HEAD`，把结果写进下表；没有 git 就把整个 `app/` 目录打包成 `code_snapshot_<日期>.zip` 放本目录（几十 KB，不是 .venv）。
2. **启动方式**：照实际命令写，不要写"按 README 启动"。

| 项 | 值 |
| --- | --- |
| 仓库／快照 | 【路径或 commit】 |
| 启动命令 | `python -m uvicorn app.main:app --reload --port 8000` |
| 数据库 | 【文件名，见 `app/main.py` 的 `DB_PATH`】 |
| 前端入口 | 【`templates/index.html` 或等价路径】 |

## 核对时的三个落点（写完代码索引要能对上）

| 结论 | 代码位置 |
| --- | --- |
| 无服务端鉴权 | `app/main.py` 全部路由均无 `Depends(...)`，登录只返回 role 供前端使用 |
| 座位唯一性靠应用层 | `create_booking()` 里的 `SELECT 1 FROM bookings WHERE room_id = ? AND status IN (...)`，表上无唯一索引 |
| 状态可任意回退 | `update_booking_status()` 只校验 `status` 是否在枚举内，不校验"从哪个状态来" |
| 责任主体写死 | `create_booking()` 的 INSERT 里 `source` 固定为 `'admin'` |
| 口令明文 | `users.password TEXT`，`login()` 用 `password = ?` 直接比对；管理员口令写死在 `login()` 内 |

> 代码会变。改完代码要回来更新这张表，否则 A.7 的"修改位置"指的是一处已经不存在的行号。
