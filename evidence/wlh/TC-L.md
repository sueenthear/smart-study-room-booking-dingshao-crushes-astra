# TASK-004 测试证据

## 基线

- 任务：TASK-004 / 基础设施、教室与统计测试（20 单元 + 10 集成）
- 负责人：王力豪　审查人：郑晨宇
- 代码版本：`7416c19de7e37bd287761fa98b8b2c4a10d1c0a8`
- 分支：`main`
- 验证时间：2026-11-26 20:19:49 +08:00
- Python：3.13.14
- 测试框架：`unittest`
- 数据库：每个用例独立临时 SQLite 文件

## 需求映射

现行基线以 `01_需求规格说明书.md` v2.0 的编号为准。任务卡中的“教室增删改、学生 CRUD/CSV、运营总览/分析”分别对应仓库现行 `FR-10`、`FR-11`、`FR-15`；旧分析报告中的 `FR-04`、`FR-14`、`FR-15` 不作为本任务编号引用。

| 用例 | 需求/规则 | 验收点 |
| --- | --- | --- |
| Unit 1-3 | S1 基础设施 | 建表完整、演示数据存在、重复初始化幂等 |
| Unit 3b | S1 基础设施 | 初始化启用 SQLite WAL |
| Unit 4-5 | S1 基础设施 | 外键开启、`busy_timeout=30000` |
| Unit 6-7 | BR-09 | 5.0 基准、每次 0.4、最低 1.0，交叉复核 |
| Unit 8-9 | BR-09 | 信用等级边界与标签完整对应 |
| Unit 10-12 | BR-12、BR-13 | 容量按实体座位汇总；全维修/部分维修状态 |
| Unit 13-14 | FR-11、FR-17、NFR-07 | 账号快照字段完整；不返回密码 |
| Unit 15-16 | S1 基础设施 | `rows_to_dict` 空结果、单行结果 |
| Unit 17-18 | BR-21（待确认）、NFR-07 | 默认解封日期跨月、跨年；当前行为仅作单元格边界测试 |
| Unit 19-20 | BR-10、FR-19 | 90 天截止与有效违约计数一致 |
| Integration 1-3 | FR-10 | 教室新增、编辑、删除 |
| Integration 4-6 | FR-11 | 学生新增、编辑、删除 |
| Integration 7 | FR-11 | CSV 批量导入及可选密码 |
| Integration 8 | FR-15 | 运营总览统计 |
| Integration 9 | FR-15 | 四类分析统计：趋势、区域、热门座位、爽约率 |
| Integration 10 | 系统入口 | 首页 `GET /` 返回 HTML/200 |

## 测试命令

```text
uv run python -m unittest tests.test_infra_王力豪 -v
```

## 原始结果

```text
test_unit_01_init_db_creates_complete_schema ... ok
test_unit_02_init_db_seeds_demo_data ... ok
test_unit_03_init_db_is_idempotent ... ok
test_unit_03b_init_db_enables_wal_mode ... ok
test_unit_04_connect_db_enables_foreign_keys ... ok
test_unit_05_connect_db_sets_busy_timeout ... ok
test_unit_06_calculate_credit_rating_formula ... ok
test_unit_07_calculate_credit_rating_cross_check ... ok
test_unit_08_credit_level_boundaries ... ok
test_unit_09_credit_level_cross_check ... ok
test_unit_10_sync_classroom_capacities_aggregates_rooms ... ok
test_unit_11_sync_classroom_capacities_all_maintenance ... ok
test_unit_12_sync_classroom_capacities_partial_maintenance ... ok
test_unit_13_account_snapshot_has_complete_status_fields ... ok
test_unit_14_account_snapshot_removes_password ... ok
test_unit_15_rows_to_dict_empty_result ... ok
test_unit_16_rows_to_dict_single_result ... ok
test_unit_17_default_blacklist_until_across_month ... ok
test_unit_18_default_blacklist_until_across_year ... ok
test_unit_19_credit_cutoff_matches_active_violation_count ... ok
test_unit_20_credit_cutoff_cross_check ... ok
test_integration_01_create_classroom ... ok
test_integration_02_update_classroom ... ok
test_integration_03_delete_classroom ... ok
test_integration_04_create_student ... ok
test_integration_05_update_student ... ok
test_integration_06_delete_student ... ok
test_integration_07_import_students_from_csv ... ok
test_integration_08_overview ... ok
test_integration_09_analytics_four_stat_groups ... ok
test_integration_10_homepage_returns_html ... ok

----------------------------------------------------------------------
Ran 31 tests in 1.035s

OK
```

## 全部回归

```text
uv run python -m unittest discover -s tests -v
```

结果：`Ran 39 tests in 4.717s`，`OK`（全仓最终回归）
