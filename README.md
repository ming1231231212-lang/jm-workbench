# JM工作台

一个在自己电脑上运行的开源内容工作台，把社区帖子与评论、视频发布、采集任务、账号和执行回执放在一起管理。

[下载 Windows 免安装版](https://github.com/ming1231231212-lang/jm-workbench/releases/latest) · [使用说明](docs/windows-portable.md) · [提交问题](https://github.com/ming1231231212-lang/jm-workbench/issues) · [MIT 许可证](LICENSE)

## 下载后怎么用

适用于 **Windows 10 / 11，64 位**。普通使用者无需安装 Python、Node 或 FFmpeg。

1. 打开上方下载页，在 Assets 中下载 `JMWorkbench-v1.1.1-windows-x64.zip`。`Source code` 是开发用源码，不是免安装程序。
2. **完整解压**到一个本地文件夹，双击 **JM工作台.exe**。
3. 添加自己的平台账号，完成登录与连接检查，再保存内容和任务配置。

首次启动是空工作台，没有维护者的账号、Cookie、密钥、内容或自动发布计划。账号权限由使用者自己取得。

| 入口 | 用途 |
|---|---|
| JM工作台.exe | 启动后台服务并打开工作台；重复打开会复用已有实例 |
| 退出工作台.exe | 结束本发行包的后台服务，保留个人数据 |
| 环境检查.exe | 查看运行状态和日志位置 |
| 使用说明.html | 离线阅读首次配置、备份和升级方法 |

数据保存到 `%LOCALAPPDATA%/JMWorkbench`，与程序目录分开。升级前先退出旧版、备份数据，再解压新版。关闭网页后后台仍会运行；电脑关机、休眠或未联网时无法执行任务。

## 有哪些功能

| 模块 | 能做什么 | 使用条件 |
|---|---|---|
| 社区发布 | 管理帖子、评论、平台账号、每日计划、执行与回执记录 | 20 个社区能力目录；自动发布、API 授权、网页交接分别标明。目录数量不代表全部支持自动发送 |
| 视频发布 | 素材上传预览、草稿、平台账号、立即与定时队列、逐账号回执 | 随包集成 SAU 必要组件，提供快手、抖音、小红书、视频号接入；需自己登录 |
| 任务与账号矩阵 | 配置关键词、采集范围、模板、账号绑定、启停与时段 | 快手基础搜索与评论有内置适配；按实际账号与平台能力执行 |
| 采集与数据中心 | 分类查看结果、筛选、分页、CSV 导出 | 其他平台采集需另行配置具备使用许可的外部爬虫环境 |
| 运行记录 | 查看发送内容、等待原因、失败原因、平台回执 | 区分已提交、结果不明与公开可见，不把请求成功当成效果证明 |
| 设置与诊断 | 浏览器、外部组件路径、服务状态和数据保存 | 仅监听本机，适合个人电脑使用 |

社区适配能力见[社区发布说明](docs/community-publishing.md)，视频接入见[内容发布说明](docs/content-publishing.md)。平台网页、账号权限和接口变化可能影响真实执行；各适配器的模拟测试不等于所有平台都已在线验收。

## 执行与数据保护

- 接收者自行配置账号、目标和内容；首次启动不自动对外发送。
- 按平台共享频次、去重与固定账号快照执行。未知回执不自动重发，平台限制不会通过换账号或换 IP 绕过。
- 后台服务异常退出时，便携监护尝试恢复；用户停止、任务暂停和平台锁仍有效。
- 验证码与网站要求的登录由本人完成。程序开放源代码不代表取得外部平台权限。
- 备份前退出工作台。不要把个人数据目录或浏览器资料跟随程序发给别人。

## 从源码开发

需要 Python 3.11+；Node 22 用于 JavaScript 测试。浏览器操作使用 Google Chrome。

```powershell
git clone https://github.com/ming1231231212-lang/jm-workbench.git
cd jm-workbench
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest
npm test
.\.venv\Scripts\python.exe -m jm_workbench
```

访问 `http://127.0.0.1:8776/`。源码模式的数据位于 `var/`，不与便携版默认数据目录混用。不要将本机服务直接暴露到公网。

- [架构与扩展点](docs/architecture.md)
- [测试与验收](docs/testing.md)
- [Windows 构建、运行与升级](docs/windows-portable.md)
- [开源发行流程](docs/open-source-release.md)
- [参与开发](CONTRIBUTING.md)

GitHub Actions 运行 Python / JavaScript 回归；Windows 发行工作流从固定运行时和依赖构建，在干净 Windows 环境运行实际 EXE 验收，校验完整文件清单与 ZIP 后上传草稿。CI 使用模拟账号和本地草稿，不对外发帖。

目标为 Windows 10/11 x64。本地实测 Windows 11，独立 CI 使用 Windows Server 2025；Windows 10 暂无真机测试记录。

## 开源许可

**JM 自有代码采用 [MIT](LICENSE)**：可以使用、修改、再分发及商业使用，保留版权声明和许可证即可。第三方组件沿用各自许可，详见[第三方说明](packaging/THIRD_PARTY_NOTICES.md)。

MediaCrawler 不包含在源码仓库或发行包中，仅保留外部接入。其上游非商业学习许可不被 JM 的 MIT 许可替代；需另行核对和取得相应使用授权。
