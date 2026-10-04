# 社区每日巡检

`scripts/community_monitor.py` 通过本机 `GET /api/health` 与 `GET /api/community/state` 检查社区运行状态，生成每天的记录、最新HTML报告和有变化时才追加的事件记录。不会读取认证令牌、Cookie或密钥，不会请求任何外部发布接口，不会重启、解锁或恢复业务任务。

默认输出：`var/community-monitor/latest.html`、`latest.md`、`latest.json`、`YYYY-MM-DD.json`、`changes.jsonl`。数据不入Git。报告包含帖子与评论正文、目标、状态、回执链接和可见性边界。HTML输出转义业务文本，结果仅提供HTTPS链接。

用户报告以平台名称和中文状态展示。网页发布后登记的链接单独统计，不加入今日自动回执数，也不推定其实际发布时间。

巡检覆盖最近200条社区内容记录，区分上海自然日帖子与评论的接收数。检查执行器停止、平台风险锁、系统原因暂停、账号检查超过24小时、任务超时、重复提交相同内容和同账号重复评论同一目标。用户主动暂停不被当作自动恢复理由。读取失败时数量记为未知，不记为0。账号检查时间仅代表上次记录，不声称当前登录有效。

仅有平台提交回执不等于公开可见。此巡检不访问公开帖子核验可见性，也不测量浏览量、网站点击和转化；报告会明确标记这些限制。`changes.jsonl` 是本地变化记录，不是Codex聊天推送。状态不变时不重复追加提醒记录。

## Windows每日任务

在项目根目录执行：

```powershell
.\scripts\Manage-CommunityMonitor.ps1 -Action Enable
.\scripts\Manage-CommunityMonitor.ps1 -Action Run
.\scripts\Manage-CommunityMonitor.ps1 -Action Status
```

任务名称 `JM Community Daily Monitor`，每天北京时间10:30。安装时验证系统时区是 `China Standard Time`。使用当前用户、普通权限、隐藏的pythonw执行；电脑开机且当前用户已登录时才能运行，错过计划后在可运行时补做。单次最长3分钟，多实例忽略。与原服务守护任务独立，不替代服务守护。

停用：`Manage-CommunityMonitor.ps1 -Action Disable`。脚本会核验同名任务是否属于当前安装，不覆盖其他程序的任务。

计划任务退出码0代表巡检程序完成；报告仍可能是warning/error，不能把程序退出码当作业务发布成功。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_community_monitor.py
```

覆盖只读HTTP契约、代理绕过、服务离线未知计数、上海日期边界、隐私字段排除、回执语义、去重、用户暂停、预算等待、未知回执、HTML转义与变化记录幂等。
