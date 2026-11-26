-- 数据库核对语句（SQLite）
-- 用法：sqlite3 app.db < db_checks.sql
-- 目的：为 02 的 A.5/A.6/A.7 与 03 的 AI-03 提供可复核的记录，不是"跑一下看看"。

.headers on
.mode column

.print '=== Q1 表与约束：varchar 之外的唯一性到底建在哪一层 ==='
SELECT name, sql FROM sqlite_master WHERE type = 'table' ORDER BY name;

.print ''
.print '=== Q2 bookings 上的索引（若没有 room_id+时段 的唯一索引，BR-01 只能靠应用层 SELECT） ==='
SELECT name, sql FROM sqlite_master WHERE type = 'index' AND tbl_name = 'bookings';

.print ''
.print '=== Q3 同座位时段重叠（预期 0 行） ==='
SELECT a.id AS id_a, b.id AS id_b, a.room_id, a.start_at, a.end_at, b.start_at AS b_start, b.end_at AS b_end
FROM bookings a
JOIN bookings b
  ON a.room_id = b.room_id AND a.id < b.id
WHERE a.status IN ('booked','checked_in') AND b.status IN ('booked','checked_in')
  AND a.start_at < b.end_at AND a.end_at > b.start_at;

.print ''
.print '=== Q4 同人时段重叠（BR-01 的判据；预期 0 行，实际有行即为缺口 V-02） ==='
SELECT a.user_id, a.id AS id_a, b.id AS id_b, a.room_id AS room_a, b.room_id AS room_b, a.start_at, a.end_at
FROM bookings a
JOIN bookings b
  ON a.user_id = b.user_id AND a.id < b.id
WHERE a.status IN ('booked','checked_in') AND b.status IN ('booked','checked_in')
  AND a.start_at < b.end_at AND a.end_at > b.start_at;

.print ''
.print '=== Q5 责任主体：bookings.source 的分布（若全是 admin，说明学生自助预约也记成了管理员） ==='
SELECT source, COUNT(*) AS n FROM bookings GROUP BY source;

.print ''
.print '=== Q6 违约与信用分是否联动（violations 增加但 rating 不变 = V-06） ==='
SELECT id, name, violations, blacklisted, rating FROM users WHERE violations > 0 ORDER BY violations DESC;

.print ''
.print '=== Q7 口令是否明文（默认口令命中数；不要 SELECT 出明文列） ==='
SELECT COUNT(*) AS plain_default_hit FROM users WHERE password = '123456aa';

.print ''
.print '=== Q8 时段合法性：起点不早于终点的记录（预期 0 行） ==='
SELECT id, room_id, start_at, end_at FROM bookings WHERE start_at >= end_at;

.print ''
.print '=== Q9 时间格式与精度（是否带时区、是否到分钟） ==='
SELECT id, start_at, end_at, created_at FROM bookings ORDER BY id DESC LIMIT 5;

.print ''
.print '=== Q10 五态分布（核对 ST-01—ST-09 是否真的被走到过） ==='
SELECT status, COUNT(*) AS n FROM bookings GROUP BY status;
