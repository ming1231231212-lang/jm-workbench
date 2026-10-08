# 参与 JM工作台

欢迎通过 GitHub Issues 提交问题、建议，通过 Pull Request 改进代码。

1. 先说明具体操作、预期和实际结果，以及工作台、Windows 和浏览器版本。
2. 截图或日志请先删除账号标识、Cookie、密钥、个人信息和发布内容。不要上传 `var/`、`%LOCALAPPDATA%/JMWorkbench/` 或浏览器资料目录。
3. 开发前阅读 `AGENTS.md` 与 `docs/architecture.md`；使用 `codex/` 分支，每个功能独立提交。
4. 运行 `python -m pytest` 与 `npm test`。平台适配器测试使用模拟数据；禁止在 CI 中登录真实账号或对外发帖。
5. 说明修改内容、测试结果和已知限制。平台目录有入口不等于实现了自动发布。

贡献的 JM 原创代码按本项目 MIT 许可证提交；引入第三方材料时保留原始许可，并说明来源。

安全问题请使用仓库 Security 页的私密漏洞报告入口；若入口不可用，不要在公开 Issue 中贴出凭据或可直接利用的敏感细节。
