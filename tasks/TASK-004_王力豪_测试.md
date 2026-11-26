# TASK-004 / 基础设施、教室与统计测试（20 单元 + 10 集成）

> 负责人：王力豪　|　审查人：郑晨宇　|　阶段：S1

```text
预期出处：01_需求规格说明书.md v2.0 的 FR/BR/AC 编号（禁止从代码倒推）
证据：每个测试结果存 evidence/TC-L*.txt，写清代码版本、环境、命令、原始结果

单元测试 20 个（含 9 个交叉复核：同函数不同断言）：
1-3   init_db：建表完整、演示数据写入、重复执行幂等
4-5   connect_db：外键 ON、busy_timeout 设置
6-7   calculate_credit_rating 交叉复核（不同断言角度）
8-9   credit_level 交叉复核（验证边界值与标签对应）
10-12 sync_classroom_capacities 交叉复核：容量汇总、全维修、部分维修
13-14 account_snapshot 交叉复核：字段完整性、脱敏验证
15-16 rows_to_dict 边界：空结果、单行结果
17-18 default_blacklist_until 边界：跨月/跨年日期计算
19-20 credit_cutoff_text 交叉复核：与 count_active_violations 截止一致

集成测试 10 个：
1-3   教室增删改（FR-10）
4-6   学生 CRUD（FR-11）
7     CSV 批量导入（FR-11）
8     运营总览接口（FR-15）
9     数据分析接口四类统计（FR-15）
10    首页 200（GET /）

运行：uv run python -m unittest tests.test_infra_王力豪 -v
状态：待准备
```
