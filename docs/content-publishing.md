# 内容发布接入

## 使用
1. 进入「账号」，查看内容发布账号；「登录 / 管理发布账号」打开原 SAU 登录管理页面。配置中的服务未运行时，在「设置 → 内容发布 → 检查 / 启动服务」启动。
2. 「内容发布 → 新建发布」中上传或选择视频，勾选账号，填写标题和话题。
3. 选择立即或定时执行。保存草稿只写本地；保存并执行自动预检并建立视频 × 账号组合，每个组合执行一次。
4. 在发布任务中查看逐账号记录、停止后续、继续或取消。素材库支持预览本地视频和删除未被草稿/队列使用的素材。

无需逐条人员审核。只有发布结果不明的异常需要核对平台记录；异常处理入口只记录核对结果，不自动重发或解锁平台。

## 实际能力与限制
| 平台 | 立即 / JM 定时 | JM 本地草稿 | 平台草稿 | 商品链接 |
|---|---|---|---|---|
| 快手 | 支持 | 支持 | 不支持 | 不支持 |
| 抖音 | 支持 | 支持 | 不支持 | 支持 |
| 小红书 | 支持 | 支持 | 不支持 | 不支持 |
| 视频号 | 支持 | 支持 | 支持 | 不支持 |

本次范围是 SAU Web API 的视频发布，不含它的 CLI 图文工具、其他 CLI 平台和视频编辑。混合选择不支持高级选项的平台时会拒绝执行，不静默忽略。单视频最多 150 MB；每批最多 10 个视频、20 个账号、50 个组合。

「已有登录记录」仅代表 SAU 存有登录资料，不声称登录态仍有效。SAU 返回通用成功响应也没有作品 ID 或可见性证明，JM 记为「已提交 · 未核验」。自动化与浏览器验收均使用模拟发送器；真实服务只做接口及目录读取，没有真实账号发布验收。

电脑休眠/关机时不能执行本机定时。到期后恢复运行会按原队列、平台间隔继续；不会绕过保护赶发。后台关闭后的 in-flight 请求记为结果不明。JM 不重复调用，平台最终状态仍须核对。

## 模块与数据
```mermaid
flowchart LR
 UI[五个主入口 / 发布表单] --> API[/api/publishing]
 API --> P[Publishing 服务 / 预检 / 队列]
 P --> DB[(JM SQLite / 本地视频)]
 P --> Guard[共享浏览器互斥 / 平台风险锁]
 Guard --> Bridge[SAUBridge / 仅本机 HTTP]
 Bridge --> SAU[SAU Flask + JM 保护补丁]
 SAU --> Platforms[快手 / 抖音 / 小红书 / 视频号]
 SAU --> Receipt[提交回执 / 未核验]
 Receipt --> DB
```

- `publishing/models.py`：发布输入、平台映射、服务地址与限额。
- `publishing/service.py`：持久队列、素材摘要、快照、预检、恢复与异常记录。
- `publishing/sau.py`：目录读取、流式上传、逐账号调用、已安装服务启动。不得使用 `/postVideoBatch` 的旧参数映射。
- `publishing/api.py`：本地 API；沿用主应用 Origin / token / Host / 版本保护。
- `web/static/publishing.js`：发布任务、素材、表单、账号和设置；`workbench.css` 定义统一界面。主应用保留旧业务交互。
- `publishing/sau_guard.py` + `scripts/install_sau_guard.py`：可备份、可重跑的 SAU 保护补丁。

新增表：`publish_media` 保存本地路径引用、SHA-256、时长与 SAU 素材引用；`sau_origin` 固定该缓存所属的服务地址和安装目录，切换服务不沿用旧缓存。`publish_batches` 保存草稿和幂等请求；`publish_jobs` 保存每个账号/视频的快照、状态、回执、计划时间及发送占位。原有业务表结构保持。

状态：draft → queued → running → submitted / unknown / failed；未执行组合可 paused/resume/cancelled。同账号、相同视频内容不因换文件名、标题或重复点击而重发。源码版本、服务配置、账号引用/名称、文件摘要变化会阻止旧队列执行。默认同平台间隔 30 分钟、24 小时最多 5 次，由设置配置；这是本地执行限制，不是平台承诺的安全额度。

## SAU 保护补丁
检查本机旧代码发现多个发布器会在点击后等待跳转超时时反复点击。接入补丁只对 `jmGuarded: true` 的 JM 请求启用：
- 首次点击前记录占位；确认按钮最多一次；结果不确定即退出重试。
- 单次发布协程最多 600 秒，取消后由 JM 按不确定状态处理；JM HTTP 等待 900 秒。
- 抖音的短信验证提示停止请求，保留用户到平台处理的流程。
- DRY_RUN 不返回可当真实提交的成功回执。
- GET `/jmGuard` 提供已加载版本握手；缺补丁的服务不能加入 JM 执行队列。

安装器根据 AST 定位具体视频方法并核验替换锚点，不覆盖用户已有其他修改；遇上游源码结构变化拒绝安装。先备份全部目标文件，再写入并检查可解析性。修改原 `sau_backend.py`、`myUtils/postVideo.py`、四个 uploader，新增 `jm_publish_guard.py`。SAU 自身其他入口不代表已具备 JM 的全部队列保护。

```powershell
# 只读预览
.venv/Scripts/python.exe scripts/install_sau_guard.py --root D:/SocialAutoUpload
# 停止原 SAU 后端、确认无正在执行发布后应用，然后重启原后端
.venv/Scripts/python.exe scripts/install_sau_guard.py --root D:/SocialAutoUpload --apply
```

## 测试与维护
```powershell
.venv/Scripts/python.exe -m pytest -ra
npm test
.venv/Scripts/python.exe scripts/verify_publishing_ui.py
```
Chrome 验收脚本自动创建随机本机端口、独立数据目录和模拟 SAU，不启动业务 worker；调用真实 ffmpeg/ffprobe，覆盖上传、预览、草稿、双平台定时、暂停继续、逐账号回执、异常核对、导航和手机布局。脚本只关闭它新建的测试标签页，报告保存在 outputs。

升级前暂停 watchdog，并核对无正在执行请求；备份原数据库、配置和程序。只有 UI/发布模块变更、`core/services/policies/adapters` 字节一致时，才可用 `scripts/upgrade_ui_revision.py` 离线迁移原 queued/waiting 快照的 revision 字段。脚本取得原 worker 锁、拒绝运行中/未知回执、先备份数据库；pending、任务状态、账号及发送历史全部保持。

升级后确认健康接口、原任务数据、SAU `/jmGuard` 和目录读取，再更新 watchdog 的版本绑定。回退代码也必须保留新发布历史和去重记录，不覆盖回旧数据库；已有不确定提交须先核对。
