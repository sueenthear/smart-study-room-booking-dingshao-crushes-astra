# Git / PR 合并流程记录

用于课堂展示完整开发流程：

1. `main`：稳定分支，只接收合并结果。
2. `feature/core-booking`：预约、座位、用户与统计 API。
3. `feature/admin-workbench`：管理员工作台页面与交互。
4. 在 GitHub 创建 Pull Request：`feature/core-booking -> main`，审核后合并。
5. 再创建 Pull Request：`feature/admin-workbench -> main`，审核后合并。
6. 本地同步：`git fetch origin`、`git checkout main`、`git pull --ff-only`。

推荐课堂展示命令：

```powershell
git log --oneline --graph --all
git branch -a
git remote -v
```

应用使用本地 `8000` 端口；`7433` 仅用于访问 GitHub 的 VPN/代理。推送前通过 Git 的 `http.proxy` / `https.proxy` 配置使用该代理端口，具体代理协议需与 VPN 客户端配置一致。
