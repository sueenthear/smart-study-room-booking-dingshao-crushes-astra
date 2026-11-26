# 证据：接口与数据库

这里的两个文件对应正文里"已核实"的三类结论：

| 结论 | 对应编号 | 证据文件 | 跑完看什么 |
| --- | --- | --- | --- |
| 接口没有身份校验，任何人都能改别人的预约 | V-01、SC-02 | `repro.ps1` 的 E1、E2 | 是否返回 200 |
| 同一时段"一人一条"与"一座一条"都没有被真正守住 | V-02、PV-02 | `repro.ps1` 的 E3、E4；`db_checks.sql` 的 Q3、Q4 | 冲突是否被 409 拒绝 |
| 状态可以任意回退，非法迁移没有被拦截 | V-04、PV-03 | `repro.ps1` 的 E5 | 第二次 PATCH 是否仍返回 200 |
| 口令与管理员凭据以明文/硬编码形式存在 | V-03 | `db_checks.sql` 的 Q7 | 命中条数、代码行 |
| 责任主体没有写进数据 | V-05 | `db_checks.sql` 的 Q5 | source 是否全是 `admin` |

## 怎么跑

```powershell
# 1) 起服务（在项目根目录，端口以实际为准）
python -m uvicorn app.main:app --reload --port 8000

# 2) 另开一个窗口
cd 附件\evidence
powershell -ExecutionPolicy Bypass -File .\repro.ps1 -Base http://127.0.0.1:8000

# 3) 数据库（路径见 app\main.py 里的 DB_PATH，通常是项目根的 .db 文件）
sqlite3 ..\..\..\app.db < db_checks.sql
```

参数（学号、座位号、预约号）按你自己的数据改，脚本顶部有默认值。

## 结果怎么存

每次运行把控制台输出另存为 `results\<日期>_<场景>.txt`，例如 `results\20261101_并发同座位.txt`。`02` 的 A.6 表里"实际结果"一栏引用这个文件名，不再靠口头描述。

> 提醒：`repro.ps1` 会真的往库里写预约和状态。跑之前备份一份数据库，跑完用备份覆盖回去，别在演示库上留脏数据。
