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

应用使用本地 `8000` 端口。远端推送的代理属于本机开发环境配置，不写入项目文档。
