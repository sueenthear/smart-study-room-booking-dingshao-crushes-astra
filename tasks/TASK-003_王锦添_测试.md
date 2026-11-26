# TASK-003 / 权限、投诉与黑名单测试（20 单元 + 10 集成）

> 负责人：王锦添　|　审查人：郑晨宇　|　阶段：S1

```text
预期出处：01_需求规格说明书.md v2.0 的 FR/BR/AC 编号（禁止从代码倒推）
证据：每个测试结果存 evidence/TC-W*.txt，写清代码版本、环境、命令、原始结果

单元测试 20 个：
1-5   normalize_blacklist_until：非黑名单/空值/日期格式/日期时间格式/非法格式
6-7   default_blacklist_until：默认 7 天后 23:59、格式正确
8-9   release_expired_blacklists：已过期释放、未过期不释放
10-14 account_snapshot：正常/受限到期/受限未到期/信用等级/密码脱敏
15-16 token_digest：相同 token 哈希一致、不同 token 哈希不同
17-18 bearer_token：合法 Bearer 头解析、缺失/非法头处理
19-20 require_self_or_admin：本人通过、他人拒绝

集成测试 10 个：
1     管理员登录（AC-01）
2     学生登录（AC-01）
3     匿名用户访问被拒
4     学生调管理员接口被拒（AC-11；TC-P01 可复用证据）
5     学生读他人数据被拒（BR-11）
6     投诉四类提交（FR-12）
7     学生只看本人投诉（BR-11）
8     管理员回复投诉，学生可见（AC-09）
9     黑名单到期自动释放（FR-14）
10    修改密码后其他会话失效（FR-01）

运行：uv run python -m unittest tests.test_auth_王锦添 -v
状态：待准备
```
