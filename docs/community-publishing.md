# 社区发布

入口：`http://127.0.0.1:8776/#community`。五个页签：帖子、评论、每日计划、账号、平台。与原“内容发布”（视频）分开，原评论/采集任务不变。

## 百度贴吧优先使用

1. 在“社区发布 → 账号”添加百度贴吧账号，填写用于区分的账号名称。
2. 点击“登录 / 打开”。JM为该账号建立独立Chrome资料目录；在贴吧页面自行登录，不向JM填写密码。
3. 返回JM“社区发布”后自动同步（同账号检查间隔30秒），成功后显示“已登录 · 已同步”。也可随时点“检查连接”。昵称可能为空或改变，身份只使用稳定的贴吧账号ID；每次发送前再次核验，切换账号会停止发送。
4. 新建帖子，选择账号，填吧名（例如“人工智能”）、标题（5–31字）、正文（最多2000字）。本版自动适配文字主题帖，不含图片、视频、话题前缀与特殊板块表单。
5. “保存草稿”只存本地；“保存并开始”按当前账号和目标创建任务。可以立即或定时、暂停、继续、取消。账号浏览器需保持连接。
6. 平台返回帖子编号后显示“已提交 · 未核验”，并能打开帖子。平台审核、公开展示和账号权限仍由贴吧决定。

当前贴吧网页为Vue/Pinia+Quill编辑器。适配器只读取页面中的登录身份与选中吧名，按页面正常操作填写并点击一次。新版页面若变化、目标吧不匹配、存在已有内容、身份变化、验证弹窗会停止。监听`/c/c/thread/add_pc`的单次回执；阻断该次操作的重复提交请求，不处理或绕过验证码。发送页面为本次创建，提交结束后关闭，避免网站验证码重试循环继续运行。

登录同步只读取此账号独立Chrome中已打开的贴吧页面，不创建标签页、不跳转、不填表、不发帖。浏览器未连接、等待登录与账号身份变化会显示不同原因。Pinia明确未登录时不使用遗留PageData冒充已登录；多个页面有不同身份时停止核验。同步不会清除平台暂停或恢复发布任务。

## 删除误建账号

在“社区发布 → 账号”点击该行的“删除”，核对账号名称、备注及核验身份后确认。同名账号按各自记录ID区分，只删除选中的工作台配置；平台账号及独立Chrome登录资料保留。

草稿正在引用该账号时，先编辑草稿更换/移除对应目标；有发布任务、已取消/失败任务或历史帖子记录时，保留账号记录并使用“编辑 → 停用”。删除不会移除帖子、发布回执、去重信息或平台暂停。确认期间账号配置改变时拒绝旧版本删除，需要刷新后重新核对。

接口为受本机token保护的`DELETE /api/community/accounts/{id}?version={version}`，重复删除同一已移除记录安全返回。删除、草稿保存及启动都在写事务中检查账号引用；旧编辑和进行中的登录同步无法重新创建已删除账号。

## 20个平台能力

|方式|平台|实际范围|
|---|---|---|
|账号浏览器提交|百度贴吧|文字主题帖与顶层评论，配置登录后执行；真实测试结果单独记录|
|官方API提交|DEV、X、Reddit、Hugging Face|需要用户自行取得可写API授权并配置；HF仅Hub模型/数据集/Space讨论，不是discuss论坛|
|网页发布交接|知乎、小红书、CSDN、掘金、V2EX、B站、微博、OSCHINA、思否、Quora、LinkedIn、Product Hunt、Medium、Indie Hackers|统一管理草稿与账号，打开网页、复制标题/正文、登记帖子链接；本版无自动提交适配器|
|本人网页发布|Hacker News|禁止自动发帖和生成式AI撰写/改写内容，不提供自动填充和提交|

这些状态不能简化成“20个平台均可一键自动发帖”。没有登录/API授权的账号不能执行自动发布。API身份读取成功不代表写权限、平台审批和公开展示已获保证。网页版最后一步由用户在平台操作，用户登记链接标为未核验。

## 接入来源（核验于2026-10-03）

- DEV：https://developers.forem.com/api/v0 （GET users/me、POST articles；为保证内容快照一致拒绝Markdown YAML frontmatter）
- X：https://docs.x.com/x-api/posts/create-post （POST /2/tweets；GET /2/users/me，用户授权令牌）
- Reddit：https://www.reddit.com/dev/api/ （GET /api/v1/me、POST /api/submit；社区名称、kind=self、OAuth）
- Hugging Face：https://huggingface.co/docs/huggingface_hub/package_reference/hf_api#create_discussion 及官方huggingface_hub源码（POST /api/{models|datasets|spaces}/{owner}/{repo}/discussions）
- HN：https://news.ycombinator.com/newsguidelines.html
- Indie Hackers：https://www.indiehackers.com/terms
- 贴吧：只读检查真实新版PC页面及公开编辑器资源；2026-10-03补充已登录账号只读实测（昵称为空的真实页面），没有发送真实测试帖。各吧内容规则单独适用。

## 数据与状态

新增表为`community_accounts / community_posts / community_jobs / community_risk`，不重写原业务表。账号凭据使用当前Windows用户DPAPI加密，API响应不返回密钥或浏览器资料路径；整个var目录排除Git。

状态：draft只存本地；queued等待时间/预算；running发送前已占位；submitted有平台帖子编号但尚未核验公开可见；manual待网页提交；recorded用户登记链接；unknown不确定且禁止自动重发；failed确认未提交；paused等待主动继续；cancelled取消未发送目标。

定时与任务快照绑定账号版本、真实身份、板块、正文和代码版本。账号/内容发生变更时不得悄悄套用到已创建的任务。相同平台+身份+板块+正文去重。所有账号共享同平台30分钟间隔；贴吧滚动24小时6次并按上海日期限制1篇主题帖+5条评论，其他社区24小时5次；这些是工作台保护预算，不是平台公布的“安全额度”，不保证账号绝不会受限。

不确定回执、权限拒绝、限流均暂停该平台。核实结果不明记录后可登记“已发布+链接”或“确认未发布+说明”；再记录平台暂停的处理说明。解除不自动恢复任务或重发。停止按钮只能阻止尚未提交的动作，已经在平台处理的请求不能撤回。

## 开发与测试

- `community/registry.py`：平台能力、板块格式、官网链接约束。
- `models.py`：账号、帖子、目标、定时输入。
- `adapters.py`：无重试HTTP客户端、身份读取、四个平台API与贴吧浏览器适配。
- `service.py`：加密账号、事务草稿/去重队列、执行器、恢复、暂停处理。
- `api.py`：本机受JM token保护的REST接口。
- `web/static/community.js + community.css`：页签、表单、逐目标状态与处理操作。
- `tests/test_community.py / test_community_adapters.py / community.test.js`：模拟发送和边界。
- `python -m scripts.verify_community_ui`：独立临时库与无生产worker的真实Chrome交互；对贴吧编辑器使用完全拦截网络的本地夹具，测试填充、回执、重复请求阻断、身份变化。

新增平台自动适配前必须补身份预检、真实协议、错误分类、帖子回执和防重复契约测试。不得仅把注册表的mode改成api/browser。

每日计划、评论与架构细节见 [community-daily.md](community-daily.md)。
