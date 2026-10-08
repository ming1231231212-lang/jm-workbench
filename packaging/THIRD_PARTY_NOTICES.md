# JM工作台 Windows 发行包：第三方组件

本包保留各组件自有许可证。JM源码与发行包按本仓库已提供的授权使用，不代表各社区授予自动发帖权限。

| 组件 | 来源与许可位置 |
|---|---|
| CPython 3.13.16 x64 嵌入运行时 | https://www.python.org/downloads/release/python-31316/ ，`runtime/LICENSE.txt`（PSF 及随附许可） |
| Python依赖 | `DEPENDENCIES.json` 记录每个 wheel 的版本和 SHA256；原始许可保留在 `runtime/site-packages/*.dist-info/` 下 |
| Playwright / Patchright | Apache-2.0；各包中的 LICENSE、NOTICE 和浏览器第三方说明均保留 |
| 随包 Chrome for Testing | Playwright 官方下载产物；浏览器目录内的 `ABOUT`, `LICENSE`, `chrome://credits` 和随附说明适用。优先使用已安装的 Google Chrome。未复制任何人的浏览器资料。 |
| Social Auto Upload | https://github.com/dreammis/social-auto-upload ，MIT，Copyright (c) 2023 dreammis，完整许可见 `vendor/sau/LICENSE`；只包含接入所需源码。JM 修改记录和原始源码哈希见 `vendor/sau/UPSTREAM.json` |
| OpenCV 的 FFmpeg 插件 | 保留 `runtime/site-packages/cv2/LICENSE-3RD-PARTY.txt` 中的 LGPL 2.1 许可。插件以独立 DLL 形式提供，允许按许可替换、逆向调试修改后的版本；对应源码和构建脚本随包保存在 `third-party-sources/`，其 SOURCES.json 固定上游提交和每份源码哈希。未使用 GPL 编码组件。 |
| OpenCV / NumPy / Requests 等 | 原始许可与第三方通知保留在各自 dist-info 及库目录中。 |

MediaCrawler **不包含在本发行包中**。本机检查到的上游许可证为 NON-COMMERCIAL LEARNING LICENSE 1.1，不能作为默认商业用途的随包组件。设置中只保留用户自行授权和配置的外接入口。

程序源码、运行时与动态依赖分别存放；无运行时在线安装脚本。平台的账号、密钥、数据库和业务内容从未作为分发组件收录。
