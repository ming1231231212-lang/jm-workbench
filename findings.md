# 实施发现

- 现有成人流程已验证精确搜索分支、视频/作者绑定、评论权限枚举、事务占位和异常停发，可复用独立实现。
- 原工作台本机连接超时根因包括原生表单导航与CDP初始化相互等待；JM全程API异步提交。
- MediaCrawler外部运行环境支持ks/dy/xhs/bili/wb/tieba/zhihu，搜索、指定内容、作者三种模式；平台业务能力逐项标注。
- 账号浏览器目录与端口不能全局写死；每账号独立配置，CDP必须核验资料目录和真实本机端点。
- 上游爬虫原配置存在94415评论上限，JM适配器必须在独立子进程内覆盖为当前任务的有限值，不能修改共享config文件。
- 现有原话术含私信导向；新陪玩模板按18+招募及真实求职场景配置，禁止与成人用品混合，保留业务目的而不迁移随机群发逻辑。

## 工具选取
planning-with-files记录持续计划；brainstorming梳理架构；find-skills完成本地目录与skills.sh检索；frontend-design仅使用已检查的通用设计说明，无需调用OpenClaw Agent。
执行工具：FastAPI/Pydantic、SQLite、Playwright/Chrome、pytest、Node自检、Git/gh。GitHub以当前已登录账户创建私有仓库，在交付阶段执行。
