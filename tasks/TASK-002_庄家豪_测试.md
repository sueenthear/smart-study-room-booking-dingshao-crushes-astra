# TASK-002 / 预约与座位测试（20 单元 + 10 集成）

> 负责人：庄家豪　|　审查人：郑晨宇　|　阶段：S1

```text
预期出处：01_需求规格说明书.md v2.0 的 FR/BR/AC/ST 编号（禁止从代码倒推）
证据：每个测试结果存 evidence/TC-Z*.txt，写清代码版本、环境、命令、原始结果

单元测试 20 个：
1-5   create_booking 校验：用户不存在/座位不存在/座位非 open/黑名单/时间格式错误
6-11  update_booking_status 状态机：五种合法迁移 + 非法迁移拒绝（ST-08/09）
12-15 update_room_status：状态枚举/使用中报修/有预约报修/恢复条件
16-17 sync_classroom_capacities：容量汇总、全维修时教室状态
18    rows_to_dict：空列表与正常数据
19    now_text：格式 YYYY-MM-DD HH:MM
20    calculate_credit_rating 交叉复核（不同断言角度）

集成测试 10 个：
1     创建预约成功（AC-02）
2     时段冲突（AC-03）
3     取消释放座位（AC-04）
4     签到占用座位（ST-10）
5     签退恢复座位（AC-06）
6     维修座位不可约（BR-03）
7     有预约不可报修（AC-07）
8     维修完成恢复（AC-08）
9     并发抢座 100 线程（AC-12；TC-P02 可复用证据）
10    座位筛选查询（FR-03）

运行：uv run python -m unittest tests.test_booking_庄家豪 -v
状态：待准备
```
