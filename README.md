# 智慧自习室预约与管理系统

基于 Python、FastAPI、SQLite 和 uv 构建的预约管理工作台，默认通过本地 `8000` 端口运行。`7433` 保留给 GitHub VPN/代理，不用于启动应用。

## 启动

```powershell
uv sync
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

浏览器打开 http://127.0.0.1:8000 。首次启动会自动创建 `app/study_room.db` 和演示数据。

## 已实现

- 座位资源状态与属性管理
- 用户、管理员预约创建与状态管理
- 签到、签退、取消预约、自动违约记录
- 预约、座位、用户、违约、投诉查询
- 手动违约登记与投诉反馈
- 柱状图、折线图、统计数据，每 10 秒自动刷新
- Git 分支、合并与推送流程记录见 `docs/git-pr-flow.md`
