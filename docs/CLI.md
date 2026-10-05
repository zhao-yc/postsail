# CLI 使用说明

项目现在提供一个统一的 CLI 入口 `sau`，当前主线已经接入：

- `douyin`
- `kuaishou`
- `xiaohongshu`
- `bilibili`
- `tencent`
- `article`：抖音、B站、百家号、今日头条、微博、知乎、企鹅号、搜狐号独立文章 API 客户端

实现说明：

- `sau_cli.py` 是当前 CLI 主入口；文章客户端实现位于 `utils/articles/cli.py`
- `sau.exe` 是安装后在 Windows 虚拟环境里自动生成的命令入口，本质上还是调用 `sau_cli.py`
- 如果需要给 OpenClaw、Codex 等 agent 使用，可参考仓库内 skill：
  - `skills/douyin-upload/`
  - `skills/kuaishou-upload/`
  - `skills/xiaohongshu-upload/`
  - `skills/bilibili-upload/`

## 安装 CLI 入口

如果你希望直接使用 `sau` 命令，而不是手动执行 `python sau_cli.py`，先在项目根目录安装一次：

```bash
uv pip install -e .
```

安装后就可以直接使用：

```bash
sau douyin --help
sau kuaishou --help
sau xiaohongshu --help
sau bilibili --help
sau article --help
```

## 安装 patchright 浏览器

Windows 下推荐先指定镜像，再安装 Chromium：

```powershell
$env:PLAYWRIGHT_DOWNLOAD_HOST="https://npmmirror.com/mirrors/playwright"; patchright install chromium
```

文章 CLI 只访问服务 API，调用端无需本地浏览器。文章后端安装 `uv pip install -e ".[web]"`，按显式 `LOCAL_CHROME_PATH`、系统 Chrome、已安装 Playwright Chromium 选择浏览器；需要回退时在后端机器运行 `python -m playwright install chromium`。详见[文章安装与服务配置](./articles.md#安装与服务配置)。

## 独立文章 CLI

先在网页「账号管理」登录文章平台，网页「文章管理」（`/articles`）和 CLI 共用原稿与任务记录：

```bash
sau article accounts --json
sau article capabilities --json
sau article import --file ./draft/article.md --title "示例教程" --cover ./draft/cover.png --json
sau article update ARTICLE_ID --revision 1 --file ./draft/article.md --json
sau article publish ARTICLE_ID --targets ./targets.json --preview --idempotency-key draft-preview-01 --json
sau article publish ARTICLE_ID --targets ./targets.json --idempotency-key draft-publish-01 --json
sau article status BATCH_ID --wait --timeout 300 --json
sau article retry TASK_ID --json
```

`ARTICLE_ID`、`BATCH_ID`、`TASK_ID` 是服务返回的字符串 ID；账号使用网页账号正整数 ID。`targets.json` 支持 `douyin/bilibili/baijiahao/toutiao/weibo/zhihu/qiehao/sohu`，可覆盖标题、封面、话题和平台 `options`。抖音支持摘要，微博支持导语和配套微博文字，企鹅号提供分类和摘要输入；所有选项以 `capabilities` 返回的 `option_fields` 及实际页面核验为准。正文支持 Markdown、HTML、纯文本，本地图片先上传；官网流程独立。

默认正式立即发布，`--preview` 可选。全部 28 个可用文章 / 图文平台支持 PostSail 后端排期：`--publish-at` 指定所选时区的时间，`--timezone` 默认 `Asia/Shanghai`；多个平台账号可在目标文件中分别指定 `schedule`。预览不接受排期。`sau article pending` 查看所有原稿的待发布任务，`reschedule` / `cancel` 使用 `--schedule-revision` 修改或取消尚未执行的任务，见[定时发布说明](./articles.md#定时发布改期与取消)。旧视频命令的 `--schedule` 不用于此入口。预览必须完成标题、正文、图片和选项读回才返回 `previewed`。正式操作先持久化 `submit_started`，再进行第一次可能提交的动作；点击超时或多步骤中断不会自动重新发布。`scheduled` 表示等待排期，`queued` 只表示任务受理，`submitted` 表示平台已接收、可能审核中，`published` 才表示取得已发表依据；`unknown` 必须人工核查后再决定重试。当前真实验收见[文章平台验证记录](./article-platform-verification.md)，不能把代码接入或离线测试通过当作发布成功。

抖音完整真实预览已通过，正式发布已取得明确提交回执，公开文章已现场核实；其余七个平台缺少验收账号，本轮未验收真实原生话题和声明。抖音正文超链接默认阻止，显式设置 `options.links_as_text:true` 后转成「原文字（完整网址）」并保留原稿与转换稿；准备顺序为先封面、后标题和正文。预览先精确阻断文章创建请求，封面完成后再安装页面按钮与快捷键保护。正式任务被动读取原生文章创建成功响应，记录 `submitted` 和内容 ID，其他任务的审核与公开链接仍须单独核对。

服务通过 `--server` 或 `OMNIPOST_API_URL` 配置，默认 `http://127.0.0.1:5409`。完整目标文件、修订检查、幂等键、结果核查和 API 说明见[独立多平台文章发布](./articles.md)。

## 抖音 CLI 子命令

```bash
sau douyin login --account <account_name>
sau douyin login --account <account_name> --headless
sau douyin check --account <account_name>
sau douyin upload-video --account <account_name> --file videos/demo.mp4 --title "示例标题" --desc "示例简介" --tags 运动,训练
sau douyin upload-note --account <account_name> --images videos/1.png videos/2.png --title "图文标题" --note "图文示例" --tags 图文,测试
```

## 快手 CLI 子命令

```bash
sau kuaishou login --account <account_name>
sau kuaishou check --account <account_name>
sau kuaishou upload-video --account <account_name> --file videos/demo.mp4 --title "示例标题" --desc "示例简介" --tags 运动,训练
sau kuaishou upload-note --account <account_name> --images videos/1.png videos/2.png videos/3.png --title "图文标题" --note "图文示例" --tags 图文,测试
```

## 小红书 CLI 子命令

```bash
sau xiaohongshu login --account <account_name>
sau xiaohongshu check --account <account_name>
sau xiaohongshu upload-video --account <account_name> --file videos/demo.mp4 --title "示例标题" --desc "示例简介" --tags 小红书,视频
sau xiaohongshu upload-note --account <account_name> --images videos/1.png videos/2.png videos/3.png --title "图文标题" --note "图文示例" --tags 图文,测试
```

## Bilibili CLI 子命令

```bash
sau bilibili login --account <account_name>
sau bilibili check --account <account_name>
sau bilibili upload-video --account <account_name> --file videos/demo.mp4 --title "示例标题" --desc "示例简介" --tid 249 --tags 足球,测试
```

补充说明：

- `creator` 之类的名字只是示例值，真正传的是用户自定义的 `account_name`
- 一个 `account_name` 对应一个账号文件，可以准备多个账号并发使用
- 浏览器平台统一元数据约定：
- 视频使用 `title + desc + tags`
- 图文使用 `title + note + tags`
- `sau bilibili ...` 会自动准备 `biliup`
- 如果本地没有 `biliup`，第一次运行会自动下载
- 如果上游 GitHub Release 有更新，运行时会先自动更新
- `sau bilibili login --account <name>` 建议由用户自己在本地真实终端里执行；如果终端里的二维码显示不完整，可直接打开当前目录下的 `qrcode.png` 扫码

## 登录二维码说明

- 抖音、快手、小红书登录过程中，CLI / uploader 可能会生成临时二维码图片
- 对普通用户来说，可以直接打开该图片扫码
- 对可操作本地文件的 agent 来说，不要只把图片路径告诉用户
- 这类二维码图片本身就是给用户扫码的，agent 应优先直接展示/发送本地图片给用户
- Bilibili 当前不走这套本地二维码图片托管链路，登录按上面的 Bilibili CLI 说明处理即可

## 定时发布

抖音、快手、小红书的图文和视频上传，以及 Bilibili 的视频上传都支持 `--schedule`。只要传了 `--schedule`，CLI 就会自动切换到对应平台的定时发布策略；不传则默认立即发布。

`sau article` 使用独立的后端排期：全部 28 个可用文章 / 图文平台通过 `--publish-at "2030-01-02T10:00:00" --timezone Asia/Shanghai` 或目标文件中的 `schedule` 指定时间。后端需运行，到点开始提交；重启后继续执行已到期的未执行任务。未知 / 不可用平台、预览排期与旧文章定时参数继续明确拒绝，不会自动改成立即发布。

```bash
sau douyin upload-video --account <account_name> --file videos/demo.mp4 --title "示例标题" --desc "示例简介" --schedule "2026-03-24 21:30"
sau douyin upload-note --account <account_name> --images videos/1.png videos/2.png --title "图文标题" --note "图文示例" --schedule "2026-03-24 21:30"
sau kuaishou upload-video --account <account_name> --file videos/demo.mp4 --title "示例标题" --desc "示例简介" --schedule "2026-03-24 21:30"
sau kuaishou upload-note --account <account_name> --images videos/1.png videos/2.png videos/3.png --title "图文标题" --note "图文示例" --schedule "2026-03-24 21:30"
sau xiaohongshu upload-video --account <account_name> --file videos/demo.mp4 --title "示例标题" --desc "示例简介" --schedule "2026-03-24 21:30"
sau xiaohongshu upload-note --account <account_name> --images videos/1.png videos/2.png videos/3.png --title "图文标题" --note "图文示例" --schedule "2026-03-24 21:30"
sau bilibili upload-video --account <account_name> --file videos/demo.mp4 --title "示例标题" --desc "示例简介" --tid 249 --schedule "2026-03-24 21:30"
```

## 运行时参数

CLI 将 `debug` 和 `headless` 拆成了两个独立维度：

```bash
--debug
--headless
--headed
```

- `--debug`: 打开调试行为，例如失败时保留更多调试信息
- `--headless`: 无头模式运行
- `--headed`: 有头模式运行

如果都不传，CLI 当前默认按 `headless=True` 运行。

补充：

- 抖音和快手的 CLI 默认都是无头模式
- 如果用户明确要求可见浏览器窗口，或确实需要人工看页面，再显式传 `--headed`

## 视频上传参数

```bash
--file videos/demo.mp4
--title "示例标题"
--desc "示例简介"
--tags 运动,训练
--thumbnail videos/demo.png
```

抖音额外支持：

```bash
--product-link https://example.com/item
--product-title 示例商品
```

Bilibili 额外要求：

```bash
--tid 249
```

- `--tid` 第一版是必填
- `--tags` 会映射到 `biliup upload --tag`
- `--schedule` 会映射到 Bilibili 所需的时间戳参数

## 图文上传参数

```bash
--images videos/1.png videos/2.png videos/3.png
--title "图文标题"
--note "图文内容"
--tags 图文,测试
```

图文上传当前限制：

- 抖音：最多 35 张图片，不支持 GIF
- 快手：支持多张图片，建议传真实不同文件，不要把同一路径重复多次
- 小红书：支持多张图片，正文 `--note` 可选，但 `--title` 建议始终显式传入

后续维护 CLI 时，优先看 `sau_cli.py`、`uploader/` 和 `skills/`。
