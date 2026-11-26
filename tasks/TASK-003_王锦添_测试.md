# TASK-003 / 权限、投诉与黑名单测试（20 单元 + 10 集成）

> 依据：《架构设计后确认与分阶段实现操作指引》模板 G
> 负责人：王锦添　|　审查人：郑晨宇　|　阶段：S1　|　版本：v2（按 2026-11-26 核对意见修订）

```text
任务编号/名称：TASK-003 / 权限、投诉与黑名单测试
负责人/审查人：王锦添 / 郑晨宇
关联阶段、需求、ADR、接口和测试：S1；FR-01、FR-12、FR-14；BR-11、BR-21、BR-09、BR-10；
  AC-01、AC-09、AC-11；TC-U01～U20、TC-I01～I10
目标：交付一套可独立运行的权限、投诉与黑名单测试，证明"越权必被拒、受限账号不可预约、
  投诉只对本人可见、未填解封日期被拒"，并作为 S2 分层重构的回归安全网。
输入基线：01_需求规格说明书.md（2026-11-01 提交版，入库后路径 docs/01_需求规格说明书.md）；
  代码版本 7416c19（main，含 PR #4）
允许修改：新建 tests/test_auth_permission.py；新建 evidence/TC-U*.txt、evidence/TC-I*.txt
禁止修改：app/ 下任何生产代码；SRS 任何条款；其他任务的测试文件；本卡所列预期结果
前置依赖：① SRS 入库并登记提交号 ② 代码基线为 7416c19 ③ BR-21 已定为"强制填写解封日期"
事务、权限、幂等约束：每例使用独立临时数据库（不得读写 app/study_room.db 演示数据）；
  会话必须经 POST /api/auth/login 取得真实 token，不得手工插入 auth_sessions
  （复用既有测试的分支若手工构造会话，须在证据中注明原因）
必执行测试：uv run python -m unittest tests.test_auth_permission -v
  （要求整批全绿 + 每个用例单独可跑）
完成标准：① 30 个用例全部通过 ② evidence/ 每例含命令、环境、代码版本、原始输出
  ③ 改动仅落在允许范围内（git status 可证）④ 郑晨宇复核通过并签字
停止条件：需改生产代码、需改 SRS 或验收预期、发现规则缺口（如某行为无需求依据）
  → 停止并反馈，不得自行调整预期或修改实现
状态：待准备
```

## 一、单元测试 20 个（TC-U01～U20）

被测单元全部是 `app/main.py` 中**无数据库依赖的纯函数**，给输入断言输出即可。

| 编号 | 被测函数 | 用例 | 关联 |
| --- | --- | --- | --- |
| TC-U01 | `calculate_credit_rating` | 0 次违约 → 5.0 | BR-09 |
| TC-U02 | 同上 | 1 次 → 4.6 | BR-09 |
| TC-U03 | 同上 | 5 次 → 3.0 | BR-09 |
| TC-U04 | 同上 | 12 次 → 触底 1.0，不再下降 | BR-09 |
| TC-U05 | `credit_level` | 5.0 → excellent／信用优秀 | BR-09 |
| TC-U06 | 同上 | 4.6 → good | BR-09 |
| TC-U07 | 同上 | 4.2 → watch | BR-09 |
| TC-U08 | 同上 | 3.4 → high_risk | BR-09 |
| TC-U09 | `credit_cutoff_text` | 返回 `YYYY-MM-DD HH:MM` 格式 | BR-10 |
| TC-U10 | 同上 | 与当前时间相差 ≈90 天（允许 ±1 分钟） | BR-10 |
| TC-U11 | `normalize_blacklist_until` | 非黑名单 → 返回 `None` | BR-11 |
| TC-U12 | 同上 | 传 `2026-12-01` → 补足为当天 `23:59` | BR-11 |
| TC-U13 | 同上 | 传 `2026-12-01 18:30` → 原样保留到分钟 | BR-11 |
| TC-U14 | 同上 | 非法格式 → 走兜底分支（**行为待 BR-21 落地后复核**，见风险 3） | BR-21 |
| TC-U15 | `account_snapshot` | 正常账号 → `days_remaining` 为 `None` | FR-14 |
| TC-U16 | 同上 | 受限未到期 → `days_remaining` > 0；受限已到期 → 为 `None` | FR-14 |
| TC-U17 | `token_digest` | 同一 token 两次摘要一致 | NFR-02 |
| TC-U18 | 同上 | 不同 token 摘要不同，且长度 64（sha256 hex） | NFR-02 |
| TC-U19 | `bearer_token` | `Bearer abc123` → `abc123` | NFR-02 |
| TC-U20 | 同上 | 缺失头／空串／不含 `Bearer ` 前缀 → 返回 `None` | NFR-02 |

## 二、集成测试 10 个（TC-I01～I10）

**5 条明确复用既有证据，不重写**；另 5 条新建。复用条目仍须在 evidence/ 写明"复用来源 + 本次验证的基线版本"。

| 编号 | 场景 | 关联 | 处理方式 | 预期 |
| --- | --- | --- | --- | --- |
| TC-I01 | 管理员登录 | AC-01 / FR-02 | **复用** `test_security_and_concurrency.py::test_login_creates_server_side_session` | 200，返回 token，`/api/auth/me` 可读 |
| TC-I02 | 学生登录 | AC-01 / FR-01 | **复用** 同上（该用例已覆盖学生角色） | 200，role=student |
| TC-I03 | 匿名访问管理接口 | AC-11 / NFR-02 | **复用** `test_admin_mutations_require_authentication_and_role` | 401 |
| TC-I04 | 学生访问管理接口 | AC-11 / BR-11 | **复用** 同上 | 403 |
| TC-I05 | 学生读他人预约／信用／投诉 | BR-11 | **复用** `test_students_cannot_read_or_write_other_students_data` | 403 |
| TC-I06 | 投诉四类提交（投诉／报修／建议／申诉） | FR-12 | **新建** | 四类均 200，落库分类正确 |
| TC-I07 | 学生只看到本人投诉 | BR-11 | **新建** | 列表仅含本人记录，不含他人 |
| TC-I08 | 管理员回复投诉，学生可见 | AC-09 | **新建** | 状态与回复对学生可见 |
| TC-I09 | 黑名单未填解封日期 → 拒绝 | BR-21（新） | **新建** | 400，提示需填写解封日期；账号未被置黑 |
| TC-I10 | 受限账号创建预约 → 拒绝 | BR-11 | **新建** | **403**（原实现为 400，按 BR-11 修正后的语义断言） |

## 三、从原卡移出的 4 项及理由

| 原条目 | 处理 | 理由 |
| --- | --- | --- |
| 单测 6-7 `default_blacklist_until` 默认 7 天 | **删除** | BR-21 已定"强制填写、不设默认值"，测即将移除的行为无意义；改由 TC-I09 在接口层覆盖 |
| 单测 8-9 `release_expired_blacklists` | **移出** | 依赖数据库连接，按指引层级属"数据库集成"而非单元测试；建议并入数据库集成专项任务 |
| 单测 19-20 `require_self_or_admin` | **移出** | 属鉴权层，与 TC-I04／I05 的接口级断言重复；如需保留请归入鉴权专项任务 |
| 集成第 10 条"修改密码后其他会话失效" | **删除并立项** | 代码 `change_password` 仅更新密码，**不失效 auth_sessions**；SRS FR-01 亦无此要求。若要实现，须先开 BR 并同步 SRS，不能作为测试预期 |

## 四、风险与迁移约定

1. **本任务是重构安全网。** 20 个单测 import 的是 `app.main` 中的函数；S2 分层重构后函数迁至服务层，届时须**按新路径迁移测试，不得删除**。迁移随重构任务一并完成，并在阶段验收单中核对用例总数未减少。
2. **不得为让测试通过而改生产代码。** 若测试暴露缺陷（如 TC-I10 的错误码），按"实现不符则修实现"处理：另开任务修复，本卡负责用当前基线记录差异并注明待实现，不得调整预期迁就实现。
3. **TC-U14 依赖 BR-21 落地。** BR-21 要求"强制填写"，则兜底分支在实际流程中不可达；本用例当前只固定函数现有行为，BR-21 实现后需复核是否保留。
4. **文件名不含中文**：`tests/test_auth_permission.py`，避免 `unittest` 模块名加载与 CI 跨平台问题。

## 五、证据文件格式（每例一份）

```text
TC编号：TC-U01
被测/场景：
代码版本：7416c19
环境：Windows 11 / Python 3.13 / uv 0.12
命令：uv run python -m unittest tests.test_auth_permission.PermissionTests.test_credit_rating_zero -v
结果：PASS（原文粘贴，含 OK / Ran 1 test）
备注：复用来源（如适用）、未覆盖分支（如适用）
```
