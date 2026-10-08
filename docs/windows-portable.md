# Windows 10/11 x64 免安装发行版

## 结构

- `JM工作台.exe` / `退出工作台.exe` / `环境检查.exe`：.NET Framework GUI 启动入口，启动内置 pythonw，无命令行操作。
- `runtime/`：官方 CPython 3.13.16 embeddable x64，隔离 `_pth`，固定依赖，不读取系统 Python 包。
- `app/jm_workbench/`：同一业务核心、静态前端、便携监护与视频发布连接器。
- `vendor/sau/`：经过白名单导入的 MIT 源码和防重复提交补丁。账号管理使用 JM 静态页面，无 Node/Vite 运行依赖。
- `browser/`：Playwright 官方浏览器分发文件。优先本机 Google Chrome，缺少时自动使用随包浏览器。
- `%LOCALAPPDATA%/JMWorkbench/`：每个 Windows 用户独立保存账号、任务、素材和日志。

## 启动和升级

监护进程持有独立数据目录的 OS 文件锁；重复打开只复用同一实例。健康接口返回数据目录指纹，防止误连同端口上的开发版。首次选择可用端口并保存，之后不改变视频接入端口以保持任务快照；端口冲突会拒绝接管外部服务。

服务崩溃后监护尝试恢复，连续启动失败后给出明确错误；停止文件控制有序退出。既有任务暂停、平台锁、未知回执和固定快照语义全部由业务核心保持。升级先退出旧包、备份用户数据，再解压新包；路径默认值迁移只更新仍由发行包管理的值，用户自定义路径保留。

视频连接器仅接受本机绑定端口、同源浏览器和 JM 私有随机令牌。删除或编辑仍有活动任务的账号会拒绝。批量提交、Cookie 导出与不受保护的上游入口不开放。素材和账号每次只允许一个，强制使用防重复提交保护。令牌仅在进程内传递，不写入公开报告。

## 可复现构建

1. 在 Windows 构建机使用 Python 3.11+，下载官方 `python-3.13.16-embed-amd64.zip`；打包脚本固定校验官方 SHA256。
2. 使用 `packaging/requirements-windows.lock` 下载 Windows CPython 3.13 wheels。`pip download --only-binary=:all: --python-version 3.13 --platform win_amd64 --implementation cp --dest <downloads>/wheels -r packaging/requirements-windows.lock`。
3. 用 Playwright 1.61.0 执行 `playwright install chromium --no-shell`，将 `PLAYWRIGHT_BROWSERS_PATH` 指向干净构建目录。
4. 执行 `python packaging/collect_codec_sources.py <downloads>/codec-sources` 保存对应视频解码源码，再执行 `python packaging/build_windows.py --downloads <downloads> --browser <browser-build> --output <new-staging>`。构建器不从现有 var、.venv、浏览器资料、数据库或业务输出复制文件。
5. 运行项目 Python/Node 回归和 `scripts/verify_portable.py --bundle <staging> --output <test-output>`，核对测试报告。
6. ZIP 发行包，计算 SHA256；上传 GitHub Release 后核对远程下载哈希。Release 必须同时说明平台登录和可见性边界。

`--refresh-source` 仅用于构建过程修改源码后的更新；最终必须再次生成文件清单并重新验收。依赖原始许可完整保留。`vendor_sau.py` 是维护用的白名单导入工具，执行前必须审核输入源码及许可；它不导入安装数据。

归档使用 `packaging/archive_windows.py`：先核对所有文件 SHA256 和白名单，再生成单一 ZIP，并完成全量 ZIP CRC 检查。`scripts/verify_portable_relocation.py` 从程序包以外运行，复用测试数据检验程序目录搬动。

大文件传输慢时，可用 `prepare_release_upload.py` 生成带固定哈希的临时分片，通过 `upload_release_parts.py` 最多六路上传到本次草稿 Release；`assemble_release.py` 在 GitHub Actions 中重新校验每片和整体 SHA256，只上传与本地测试 ZIP 完全相同的文件，再删除本次分片。该流程只处理草稿，不自动公开发布，也不触碰其他版本的资产。

## 功能边界

本地配置、任务、模板、数据、回执、社区工作流、快手基础采集/评论与视频发布接入随包提供。其他平台采集需要外接环境；MediaCrawler 因许可证限制未随包提供。20 个社区是能力目录，未实现自动发布的平台仍按能力标记使用人工网页交接，不能宣称全平台自动发布成功。

验证码和平台限制不会被绕过；账号权限及平台页面需要接收者自行登录后核验。本地模拟成功不等同于真实网络提交成功，更不等同于公开可见。
