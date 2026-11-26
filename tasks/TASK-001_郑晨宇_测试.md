# TASK-001 / 信用分与违约规则测试（20 单元 + 10 集成）

> 负责人：郑晨宇　|　审查人：王锦添　|　阶段：S1

```text
输入基线：仓库提交 7416c19（main，含 PR #4 取消预约修复）
预期出处：01_需求规格说明书.md v2.0 的 FR/BR/AC/ST 编号（禁止从代码倒推）
运行环境：Windows 11 / Python 3.12.2 / uv 0.13.1
证据：每个测试结果存 evidence/TC-C*.txt，写清代码版本、环境、命令、原始结果

单元测试 20 个：
1-4   calculate_credit_rating：0/1/12/13 次违约 → 5.0/4.6/1.0/1.0
5-9   credit_level：5.0/4.5/4.0/3.5/3.4 五档 → excellent/good/watch/risk/high_risk
10-12 count_active_violations：89 天/90 天/91 天记录的计入判定
13-14 sync_user_rating：同步后 users.rating 与计算值一致
15-16 backfill_violation_history：历史违约补录条数正确
17-18 credit_cutoff_text：90 天截止日期计算正确
19-20 calculate_credit_rating 舍入：小数位保留 2 位

集成测试 10 个：
1-2   违约→扣分联动（TC-S03 可复用）
3     迟到 15 分钟边界（Q-05 已关闭）
4     90 天恢复后信用分回升（AC-10）
5     信用档位读取
6     管理员手动登记违约后信用分同步
7     黑名单到期自动解封（FR-14）
8     受限账号不可创建预约（BR-11）
9     登录时信用分同步
10    违约记录按用户过滤（FR-12）

运行：uv run python -m unittest tests.test_credit_zcy -v > evidence\TC-C_zcy_全部.txt 2>&1
状态：完成（2026-11-26）—— Ran 30 tests，29 通过 + 1 expected failure（BR-11 待同步的 I08）
证据：evidence/TC-C_zcy_全部.txt（含版本/环境/命令/原始输出）
```
