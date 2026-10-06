# 独立多平台文章发布

PostSail 接收准备好的原稿，通过 28 个平台能力分别提交原生文章或图片笔记。原生文章包括抖音、B站、百家号、今日头条、微博、知乎、企鹅号、搜狐号、一点号、大鱼号、网易号、AcFun、快传号、雪球号、京东长文章、豆瓣、CSDN、简书、车家号、易车号、懂车号和微信公众号。小红书、快手、视频号、京东图文、小红书商家号和淘宝光合使用「文字描述 + 有序图片」，转换要求见下文。官网沿用独立流程；文章功能不自动抓取官网，也不依赖官网发布结果。

京东长文章使用 `jingdong`、账号类型 18 和 `https://dr.jd.com/n/publish-article.html`（`style=0`）；京东图文使用 `jd`、账号类型 26 和 `https://dr.jd.com/n/publish-graphic.html`（`style=25`）。两者的正文、封面和选项不同，不自动互换。

平台代码接入与真实账号验收分别记录。2026-10-01 已现场验证抖音单篇文章的标题、完整正文、三张正文图顺序及高清封面，预览和正式提交均通过，[抖音公开文章](https://www.douyin.com/article/7691535675165871406)已独立打开核实；其余 27 个能力缺少验收账号，`live_verified:false`。京东长文章和三个汽车平台补充了官方组件的离线浏览器验证，仍未执行真实账号登录、素材上传或发布。抖音本次未验收真实原生话题或声明，不能据此认定全部专属选项已通过。具体过程、平台限制和证据见[文章平台验证记录](./article-platform-verification.md)。

文章发布使用 Web 后端保存的账号 ID。现有视频 CLI 的账号文件和参数保持不变。先在网页完成目标平台登录，再运行 `sau article accounts --json` 查找可用账号。默认立即发布；全部 28 个可用文章 / 图文能力共用后端排期，覆盖原生文章与图片笔记。排期由 PostSail 后端执行，不使用平台原生定时控件；真实账号验收状态仍单独记录。

旧文章入口会按内容复用原稿；这份原稿经网页或新 API 编辑后，再发送旧请求会返回修订冲突，须从文章管理或 `sau article` 读取最新稿件发布，避免使用非预期正文。

## 安装与服务配置

CLI 由项目原有安装入口提供：

```bash
uv pip install -e .
sau article --help
```

CLI 使用 `requests` 调用文章 API，不要求调用端安装 Flask 或本地启动浏览器。实际发布浏览器在运行 Web 后端的机器上启动，沿用项目浏览器配置。

运行后端的机器安装 Web 依赖，然后启动服务：

```bash
uv pip install -e ".[web]"
python sau_backend.py
```

文章浏览器选择顺序为：显式配置的 `LOCAL_CHROME_PATH` → 系统 Chrome → Playwright 已安装的 Chromium。显式路径无效时提示修正配置，不会忽略该设置；未配置路径且系统 Chrome 未安装时才回退 Chromium。需要 Chromium 回退时，在后端所在机器安装：

```bash
python -m playwright install chromium
```

这是文章适配器使用的 Playwright Chromium，与视频流程的 `patchright install chromium` 分开安装。两者都不要求所有用户必须安装系统 Chrome。`ARTICLE_BROWSER_HEADLESS` 控制文章浏览器显示，`ARTICLE_RENDER_FONT` 指定表格、代码截图字体，`ARTICLE_PREVIEW_SECONDS` 可让预览在截图后保留浏览器一段时间（默认 0 秒）。

网页侧栏的「文章管理」（路由 `/articles`）提供文章列表、Tiptap 富文本编辑、正文图片和封面上传、平台配置、发布记录以及任务核查。哈希路由访问示例为 `http://localhost:5173/#/articles`；编辑器本身不上传到内容平台，正式发布由后端任务执行。

服务地址按 `--server`、`OMNIPOST_API_URL`、`http://127.0.0.1:5409` 的顺序选择。连接参数可以写在 `article` 后，也可以写在具体命令后。

```bash
sau article --server http://127.0.0.1:5409 --json accounts
sau article accounts --server http://127.0.0.1:5409 --json
```

`--request-timeout` 控制单次 API 请求超时，默认 30 秒。后端存储账号会话、原稿、图片和发布记录，服务应部署在受信任网络。不要把未设置访问保护的服务直接开放到公网。

## 任务中心与异常提醒

网页侧边栏「任务中心」（`/#/article-tasks`）汇总全部原稿的文章 / 图文任务，覆盖正式发布和平台预览。列表按最近更新排序，支持冻结标题、平台、账号、状态、执行方式、创建时间范围和仅未读提醒筛选。标题来自任务创建时的内容，编辑原稿不会改变历史任务标题。顶部计数沿用其他筛选条件，但不受状态筛选影响。视频任务仍使用现有发布中心。

任务详情展示进度、执行次数、时间、平台状态和截图 / 回执。可以直接改期、取消、重试确定未提交的任务、核查结果不确定或已受理的任务，并跳转到对应原稿或账号登录入口。登录入口需用户点击「重新登录此账号」后才开始登录；任务查询和提醒已读操作均不发布内容。内容校验失败须修正原稿后重新提交，任务快照不会被编辑后的原稿替换。

`failed`、`needs_action`、`unknown` 状态产生持久化异常提醒，后端恢复中断任务时也会产生提醒。顶部「发布提醒」显示未读数量。任务退出异常状态时，旧提醒自动结束；重试后再次失败会生成新的提醒。标记已读只改变提醒记录，不确认发布结果，也不解锁重试。人工核查为未发布后，任务可以按既有规则重试，核查动作自身不生成新的失败提醒。升级时为当前尚未核查的异常任务补建一次提醒，保留原任务状态与内容。

浏览器桌面通知默认关闭，用户在任务中心显式开启并获得浏览器授权后才使用。工作台打开期间每 15 秒查询提醒，仅提示新事件，初次观察建立基线，不集中弹出旧提醒；关闭网页后不发送桌面通知。已读状态保存在后端数据库，桌面通知偏好和事件游标保存在当前浏览器。任务中心列表只在页面可见时刷新。此功能不向邮件、机器人或其他外部渠道发送消息。

任务中心 API：

| 接口 | 用途 |
| --- | --- |
| `GET /api/article-publish-tasks?scope=all` | 分页查看全部任务；默认 `scope=pending` 保持旧待发布接口行为 |
| `GET /api/article-publish-tasks/<id>` | 单个任务详情，含冻结标题、平台名称、账号名称及允许的操作 |
| `GET /api/article-task-notifications` | 分页查看仍有效的未读提醒，返回 `items,unread,latest_id,page,page_size` |
| `POST /api/article-task-notifications/<id>/read` | 标记单条提醒已读，重复操作安全 |
| `POST /api/article-task-notifications/read` | 请求体 `{ "through_id": 123 }`，将已观察到的事件编号及更早有效提醒标记已读；更晚到达的新提醒保留未读 |

全量任务查询支持 `q`（冻结标题，最多 200 字）、`platform`、`account_id`、`mode=publish/preview`、`status`、`unread=0/1`、`created_from`、`created_before`、`page` 和 `page_size`（1–100）。状态支持各实际任务状态，以及 `attention`（失败 / 需人工处理 / 结果不确定）、`pending`（排期 / 排队）。时间参数必须包含 UTC 偏移，例如 `2030-01-02T00:00:00+08:00`；开始包含、结束不包含，按任务创建时间筛选。列表返回 `items,total,page,page_size,summary`；详情和列表不返回 Cookie、内部内容快照或准备后的正文。每个任务的 `unread_notification_id` 可用于单条已读操作。现有改期、取消、重试和核查 API 与 CLI 继续适用。

新增验证使用临时 SQLite 和模拟发布执行器，覆盖全量筛选与分页、冻结标题、提醒持久化与升级补建、并发已读边界、重试新事件、提交前后中断恢复，以及未知结果禁止重试。前端通知游标、核查输入、真实 Vue 组件的内存渲染和通知副作用有自动测试；浏览器启动在当前云环境被限制，页面点击流程、真实桌面通知及真实平台发布仍需对应环境验收。

```sh
.venv/bin/python -m unittest tests.test_article_task_center -q
cd sau_frontend
node tests/articleTasks.test.js
node tests/articleTaskRendering.test.js
npm run build
```

## 定时发布、改期与取消

网页选择任一可用文章 / 图文平台的账号后，可分别设置「立即发布」或「定时发布」，填写时间及 IANA 时区。默认时区为 `Asia/Shanghai`，可选择或输入其他时区。同一批次可以同时包含不同平台的立即发布账号和不同时间的定时账号；仅预览会立即执行，不接受排期。平台被标记为 `available:false` 时，不接受新排期或改期，尚未执行的旧任务仍可取消。

后端到点开始准备并提交内容，公开时间由平台审核决定。执行器串行处理任务，排期表示最早开始时间，可能因其他任务、账号验证或网络状况延后。后端应持续运行；重启后未到期任务继续等待，已到期且尚未执行的任务按原排期顺序执行。到期时重新检查账号绑定、会话文件及实际平台登录和权限，失败会显示具体原因，不会将请求受理当作已发表。

排期冻结提交时的原稿修订、平台覆盖项和素材。之后编辑原稿不改变计划，改期也只修改执行时间。需要使用新内容时，先取消尚未执行的任务，再保存新修订并重新提交。「待发布」列表汇总全部原稿的排期和排队任务，分页查看；开始执行后不能改期或取消，提交后不确定的结果仍须人工核查。

```bash
sau article publish ARTICLE_ID --platform zhihu --account-id 1 \
  --publish-at "2030-01-02T10:00:00" --timezone Asia/Shanghai \
  --idempotency-key draft-scheduled-01 --json
sau article pending --page 1 --page-size 20 --json
sau article reschedule TASK_ID --publish-at "2030-01-03T18:00:00" \
  --timezone Asia/Tokyo --schedule-revision 0 --json
sau article cancel TASK_ID --schedule-revision 1 --json
```

示例时间需要替换为实际未来时间。`--schedule-revision` 使用最新 `pending` 或 `status` 返回的 `schedule_revision`，初始为 `0`，每次改期或取消递增；陈旧版本返回 `409`，避免覆盖其他窗口或 CLI 的修改。取消后需要重新提交时使用新的幂等键；复用原键只查询原批次，不会恢复取消的任务。

多账号目标文件可为每个目标单独指定 `schedule`；API 顶层 `schedule` 是批次的公共默认值，目标的 `schedule:null` 明确表示立即发布：

```json
[
  {"platform":"zhihu","account_id":1,"schedule":{"publish_at":"2030-01-02T10:00:00","timezone":"Asia/Shanghai"}},
  {"platform":"xiaohongshu","account_id":2,"schedule":{"publish_at":"2030-01-03T18:00:00","timezone":"Asia/Tokyo"},"overrides":{"options":{"flatten_content":true}}},
  {"platform":"douyin","account_id":3,"schedule":null}
]
```

`schedule` 必须为包含 `publish_at` 和 `timezone` 的对象，时间必须包含日期和时分且晚于当前时间。服务器统一保存 UTC，不使用服务器或浏览器的默认时区推断。带 UTC 偏移的时间必须与所选时区相符；夏令时跳过的时间会被拒绝，回拨重复时间需通过 API/CLI 明确偏移，例如 `2030-11-03T01:30:00-04:00` 与 `America/New_York`。完整依赖含 `tzdata`，Windows 或无系统时区数据库的机器也可使用这些时区。

旧视频参数 `publish_date` / `enableTimer`、旧文章兼容入口、平台 `overrides` / `options` 内的原生定时参数继续拒绝。排期不能藏在平台内容覆盖项中。无效时间、预览排期或未知 / 不可用平台的排期会使请求整体返回 `400`，不会悄悄将其他账号立即发布。普通内容校验仍按账号独立记录结果。各平台的标题、封面、话题、声明、商品、双封面等要求，以及富文本转图片笔记时的明确转换选择，均沿用立即发布校验；创建排期不会自动补选或忽略这些字段。公众号等平台仍可能在到期执行时要求管理员扫码或其他人工操作，遇到这种情况会按实际阶段记录为需处理或结果待确认。

## 原稿与图片

导入支持 UTF-8 的 `.md` / `.markdown`、`.html` / `.htm`、纯文本文件；也可以用 `--format markdown|html|text` 显式指定。标题独立提供，不会自动使用 Markdown 的第一个标题。原稿修订号从后端取得，更新原稿不改变已经创建的发布任务快照。

```bash
sau article import --file ./draft/article.md --title "示例教程" --cover ./draft/cover.png --tags 技术,教程 --json
sau article list --json
sau article get ARTICLE_ID --json
sau article update ARTICLE_ID --revision 1 --file ./draft/article.md --title "修订后的教程" --json
sau article update ARTICLE_ID --revision 2 --clear-cover --tags "" --json
```

`update` 只修改明确传入的字段，未提供的字段保留原值；不提供 `--revision` 时先读当前修订，再通过 `expected_revision` 做并发检查。如果另一位用户已经编辑，后端拒绝更新，调用者需要重新读取原稿。

正文可以包含如下图片：

```markdown
![本地图片](images/example.png)
![含空格的文件名](<images/示例 图片.png>)
![公开图片](https://example.com/images/public.png)
![引用图片][illustration]

[illustration]: images/example.png
```

```html
<p>正文段落</p>
<img src="images/example.png" alt="示例图片">
```

CLI 会先校验全部本地正文图片，再上传到素材接口，并把引用替换为 `/api/article-assets/{id}/content`。同一次导入中的同一文件只上传一次。Markdown 围栏、缩进代码、行内代码中的图片示例不上传。正文图片必须处于正文文件目录或其子目录，目录穿越和指向目录外的符号链接会被拒绝；API 不读取调用者提供的任意服务器文件路径。封面通过 `--cover` 显式选择，可位于调用端的其他目录。

公开 HTTP/HTTPS 图片由后端下载并校验，原稿最终引用项目素材，不依赖远程图片长期可用。后端限制非公开地址、重定向目标、文件类型、大小和下载超时。图片上传成功后若后续原稿保存失败，已上传素材可能暂时未被引用，可调用 `DELETE /api/article-assets/{id}` 清理。文章素材尚无独立管理页面；已被原稿或任务快照引用的素材不允许删除。

平台封面可以先独立上传，然后在平台覆盖项中引用素材 ID：

```bash
sau article asset --file ./draft/zhihu-cover.png --json
sau article asset --url https://example.com/images/cover.png --json
```

## 选择账号与平台覆盖项

可执行的平台标识为 `douyin`、`bilibili`、`baijiahao`、`toutiao`、`weibo`、`zhihu`、`qiehao`、`sohu`、`yidian`、`dayu`、`netease`、`acfun`、`kuaichuan`、`xueqiu`、`jingdong`、`douban`、`csdn`、`jianshu`、`chejiahao`、`yiche`、`dongchedi`、`xiaohongshu`、`kuaishou`、`tencent`、`wechat`、`jd`、`xiaohongshu_merchant`、`taobao`。调用前检查当前能力接口的 `available` 和 `reason`。账号 ID 使用 `accounts` 返回的 `id`，不要填 CLI 视频命令中的 `account_name`。旧分支账号若显示「平台待确认」，先在账号管理确认绑定，参见[迁移说明](./account-platform-migration.md)。

```bash
sau article accounts --json
sau article accounts --platform zhihu --json
sau article capabilities --json
```

当前文章约束如下。它们是本版本的配置限制，实际账号页面仍会检查权限和控件；平台更新后以能力接口及页面提示为准。

| 平台 | 账号类型 | 原生内容 | 标题字数 | 封面 |
| --- | --- | --- | --- | --- |
| 抖音 `douyin` | 3 | 原生文章 | 1–30 | 必填，宽高均至少 500px，≤20MB |
| B站 `bilibili` | 6 | 专栏 / 长图文 | 1–30 | 可选，至少 600×336px，≤20MB |
| 百家号 `baijiahao` | 5 | 文章 | 2–64 | 必填，≤5MB |
| 今日头条 `toutiao` | 7 | 文章 | 1–30 | 可选，≤20MB |
| 微博 `weibo` | 10 | 头条文章 | 1–32 | 必填，≤10MB |
| 知乎 `zhihu` | 9 | 文章 | 1–100 | 可选，≤10MB |
| 企鹅号 `qiehao` | 11 | 文章 | 5–64 | 可选，≤10MB |
| 搜狐号 `sohu` | 8 | 文章 | 5–72 | 可选，宽高分别大于 450px 和 300px，≤10MB |
| 一点号 `yidian` | 12 | 文章 | 5–64 | 必填，≤20MB |
| 大鱼号 `dayu` | 13 | 文章 | 1–50 | 可选，≤20MB |
| 网易号 `netease` | 14 | 文章 | 1–300（原稿上限） | 必填，≤20MB |
| AcFun `acfun` | 15 | 文章投稿 | 1–50 | 必填，≤20MB |
| 快传号 `kuaichuan` | 16 | 文章 | 1–300（原稿上限） | 必填，≤20MB |
| 雪球号 `xueqiu` | 17 | 长文章 | 9–100 | 可选，≤20MB |
| 京东长文章 `jingdong` | 18 | 原生文章（`style=0`） | 15–27 | 必填，每任务 1 张，10:7、至少 600×420px、≤5MiB；不能与正文首图为相同素材或相同文件内容 |
| 豆瓣 `douban` | 19 | 日记文章 | 1–300（原稿上限） | 不支持独立封面 |
| CSDN `csdn` | 20 | 博客文章 | 1–300（原稿上限） | 必填，≤20MB |
| 简书 `jianshu` | 21 | 文章 | 1–300（原稿上限） | 不支持独立封面 |
| 车家号 `chejiahao` | 22 | 原生长文 | 原生加权 6–30 字，英文等半字计数 | 横版 4:3、至少 560×420px；竖版 3:4、宽度至少 560px、高度至少 420px，建议 600×800px；各 ≤10MiB |
| 易车号 `yiche` | 23 | 文章 | 5–28 | 横版 3:2；竖版 3:4 或 4:3；各 ≤10MiB、宽度 ≤5000px |
| 懂车号 `dongchedi` | 24 | 文章 | 2–30，至少 2 个汉字 | 横版 4:3、至少 532×399px；竖版 3:4、至少 534×712px；各 ≤20MiB |
| 小红书 `xiaohongshu` | 1 | 图片笔记 | 1–20 | 可选，未在正文图片中时放到图片列表首位 |
| 快手 `kuaishou` | 4 | 图片笔记 | 1–90，作为描述首行 | 可选，未在正文图片中时放到图片列表首位 |
| 视频号 `tencent` | 2 | 图片笔记 | 1–16 | 可选，未在正文图片中时放到图片列表首位 |
| 微信公众号 `wechat` | 25 | 公众号文章 | 1–64 | 必填，≤10MB |
| 京东图文 `jd` | 26 | 图片笔记（`style=25`） | 5–20，页面限制另行校验 | 可选，首图生成 3:4 封面，每图 ≤5MB |
| 小红书商家号 `xiaohongshu_merchant` | 27 | 商家图片笔记 | 1–20 | 可选，未在正文图片中时放到图片列表首位 |
| 淘宝光合 `taobao` | 28 | 图片笔记 | 1–30 | 首图作为封面；每图至少 720×720px，≤20MB |

表中的 300 字是 PostSail 原稿标题上限，并非已确认的平台限制；相应能力字段为 `title_limit_confirmed:false`。执行时还会读取标题输入框的实际限制，超过限制会停止，不截断标题。表中的 20MB 封面上限是本版本的素材检查配置，平台页面仍可能有更严格要求。大鱼号与 AcFun 的正文 HTML 上限配置为 50000 字符。

三个汽车平台的约束结合蚁小二文章契约与 2026-10-03 只读取得的官方编辑器脚本；公开源码研究不等于真实账号验收。车家号按原生 UTF-16 码元计数：数值大于 256 计 1 字，其余计半字；标题须为 6–30 字，纯 ASCII 标题对应 12–60 个字符，不要求至少六个汉字。正文使用原生加权 10–100000 字限制，不能将其误写为 HTML 源码长度。易车号正文 HTML 上限配置为 8000 字符，竖封面接受 3:4 或 4:3，比例容差为 0.01，未设置独立的最低像素。三个平台均要求独立横、竖封面，不继承原稿默认 `tags`；尚未开放原生话题处理，不把普通文本作为原生话题。三个原生适配器均已开放执行；真实账号权限与实际发布仍需逐平台验收。

豆瓣、简书不继承原稿的独立封面；显式指定这两个平台的 `cover_asset_id` 会被拒绝，图片请放入正文。一点号、大鱼号、网易号、雪球号、京东长文章和简书不支持独立话题字段，因此不继承原稿默认 `tags`；显式非空覆盖也会被拒绝。微信公众号和淘宝光合也不支持非空 `tags`，可使用 `overrides.tags:[]` 明确清空。CSDN 至少需要一个标签，AcFun 最多一个话题；其余原生选项仍须在实际控件中设置并读回。

封面仅接受 JPEG 或 PNG。当前类型 `12`–`24` 保留 main 分支的平台含义；微信公众号、京东图文、小红书商家号、淘宝光合分别使用 `25`–`28`，微信视频号仍为 `2`。旧 work 分支类型 `12`–`16` 与 main 的含义冲突，须按[账号平台迁移](./account-platform-migration.md)确认归属，不能仅按旧数字推断。仅用于文章 / 图片笔记的账号类型会明确拒绝视频请求；类型登记不代表账号已有内容发布权限。无图形窗口的服务器可导入已登录的浏览器会话。两个京东入口分别核实对应权限。同一 B站账号可供视频和文章使用：视频保留 `biliup` 会话，文章读取时只在内存转换为浏览器会话。标准 Playwright `storage_state` 和 `biliup` JSON 均可通过网页导入，导入会校验结构、目标域名和实际登录状态，不能仅凭 Cookie 存在认定可发布。

`capabilities` 返回每个平台的 `option_fields`，网页据此展示专属字段，API 和 CLI 使用同一平台定义。主要选项如下：

| 平台 | `options` 字段 | 实际处理 |
| --- | --- | --- |
| 抖音 | `summary`、`links_as_text`、`statement` | 摘要最多30字；显式启用链接转文字；声明按平台原文查找 |
| B站 | `statement` | 当前编辑器未提供可配置分区；话题通过正文原生标签节点处理 |
| 百家号 | `ai_generated` | 使用原生 AI 内容声明并检查选中状态 |
| 今日头条、知乎、搜狐号 | `statement` | 仅接受能力接口列出的声明并读取选中状态 |
| 微博 | `summary`、`publish_text`、`statement` | 导语最多44字；配套微博文字留空使用文章标题 |
| 企鹅号 | `category`、`summary`、`statement` | 精确分类候选；摘要与声明必须有可核实的原生控件 |
| 一点号、大鱼号 | `statement` | 按平台显示的完整声明匹配并读回 |
| 网易号 | `statement`、`original` | 原生声明与原创开关须核实选中状态 |
| AcFun | `summary`、`category`、`original`、`source_url` | 摘要最多200字；分类必填；`original:false` 表示不声明原创，不强制填写原文链接 |
| 快传号 | `original` | 设置原生原创开关并读取状态 |
| 雪球号 | `visibility`、`statement` | 可见范围为「公开」或「仅自己可见」；声明精确匹配 |
| 豆瓣 | `original`、`visibility` | 日记原创声明及「公开」/「仅自己可见」 |
| CSDN | `summary`、`create_type`、`source_url`、`statement` | 摘要、创作类型必填；类型为「原创」/「转载」/「翻译」，后两者必须提供原文链接；选项在发布设置中读回 |
| 简书 | 无 | 新建独立稿件，确认新稿 ID 后才填写，不覆盖打开的旧稿 |
| 京东长文章 `jingdong` | `category` | 可选，每任务选择 1 个精确的「一级/二级/三级」分类路径，逐层匹配原生标签类型并读回；不接受普通 `tags` |
| 小红书、快手、视频号 | `flatten_content` | 富文本转为图片笔记时必须明确启用；不提供创作声明选项 |
| 微信公众号 | `author`、`summary` | 作者最多 8 字，摘要最多 120 字；标题、正文和独立封面分别读回 |
| 京东图文 `jd` | `flatten_content`、`product_links` | 商品可选，最多 10 个 SKU 或京东商品链接，逐项精确核对；不使用长文章的分类字段 |
| 小红书商家号 | `flatten_content`、`product_id`、`shop_name` | 商品 ID 与完整店铺名称必填，分别最多 64 字和 100 字；不自动选首个商品 |
| 淘宝光合 | `flatten_content`、`statement` | 创作声明必填，使用下文六个原生选项之一；不支持话题或商品关联 |

三个汽车平台支持以下专属覆盖项：

| 平台 | `options` 字段 | 实际处理 |
| --- | --- | --- |
| 车家号 | `vertical_cover_asset_id`、`original`、`first_publish`、`links_as_text`、`agree_upload_terms`、`content_type` | 独立竖封面必填；原创、首发及链接转文字须显式设置；必须明确同意上传条款；页面要求时选择「非商业内容」或「商业内容」 |
| 易车号 | `vertical_cover_asset_id`、`declaration`、`source_url`、`allow_forward`、`allow_abstract` | 独立竖封面必填；声明为「内容无需标注」「含AI生成内容」「含虚构演绎内容」「内容含营销信息」「个人观点，仅供参考」「内容为转载」之一；转载必须填写 HTTP/HTTPS 来源链接；同意转发与生成摘要均默认关闭 |
| 懂车号 | `vertical_cover_asset_id` | 独立竖封面必填 |

`vertical_cover_asset_id` 是 `type:asset` 的字段，只接受已经上传的素材 ID。先用 `sau article asset --file ./draft/vertical-cover.png --json` 上传，再将返回的 ID 保存到原稿的 `platform_options.<平台>.options.vertical_cover_asset_id`；横版封面仍使用对应的 `cover_asset_id`。服务不会把横封面自动裁剪成竖封面，也不接受服务器文件路径作为素材 ID。原稿的平台默认配置和任务快照都会保护竖封面素材引用，已引用的素材不能删除。执行时会核对本次上传结果、原生表单和可见预览，任一不一致都会停止。

易车号声明以当前原生页面的六个选项为准。早期登记的「不声明」「内容来源网络」「AI生成」「引用站内」不自动映射为新声明；已有原稿或任务需要重新选择对应选项，避免改变原作者声明。`allow_forward` 表示同意转发，`allow_abstract` 表示同意生成摘要，未明确启用时保持关闭。

易车号竖封面通过原生编辑组件保留完整画面；组件可能压缩或缩放图片，不能保证上传后像素尺寸及编码完全不变。系统会核对完整裁剪范围、已生成预览、本次上传回执和提交素材键。

车家号要求用户阅读并明确同意《汽车之家内容上传服务条款》《汽车之家联合共创须知》，对应 `agree_upload_terms:true`，默认关闭。`content_type` 仅接受「非商业内容」或「商业内容」；目标账号出现必选控件时必须提供，不能由系统推断文章属性。

车家号标题不支持 Emoji 等原生控件禁止的特殊符号；英文半字计数不能用于绕过该限制。

文本声明字段不代表任意声明均可用：页面没有精确选项、话题候选没有成为原生选中项、封面仅有本地预览却缺少上传依据，都会停止为 `needs_action`，不会忽略该选项继续提交。企鹅号出现必填内容自主声明时，需要在平台覆盖项中指定页面显示的声明。账号已登录也可能因未实名、等级、发文额度或文章权限而无法打开编辑器；实际编辑器可用且内容完整读回后才允许继续。

文章、素材、批次和任务的 ID 是不透明字符串（当前为 32 位 UUID 十六进制值），账号 ID 和修订号是正整数。命令示例中的 `ARTICLE_ID`、`BATCH_ID`、`TASK_ID`、`ASSET_ID` 均替换为服务返回的实际值。

多个平台推荐使用目标文件。以下 `targets.json` 中的账号和素材 ID 是占位示例，使用前替换为服务实际返回的 ID；分类等平台值也须与目标账号实际页面一致。

```json
[
  {
    "platform": "baijiahao",
    "account_id": 2,
    "overrides": {
      "title": "百家号标题",
      "cover_asset_id": "ASSET_ID",
      "tags": ["技术"],
      "options": {"ai_generated": false}
    }
  },
  {
    "platform": "zhihu",
    "account_id": 3,
    "overrides": {"options": {"statement": ""}}
  },
  {"platform": "toutiao", "account_id": 4},
  {"platform": "sohu", "account_id": 5},
  {
    "platform": "douyin",
    "account_id": 6,
    "overrides": {
      "cover_asset_id": "ASSET_ID",
      "options": {"summary": "示例文章摘要", "links_as_text": true}
    }
  },
  {"platform": "bilibili", "account_id": 7},
  {
    "platform": "weibo",
    "account_id": 8,
    "overrides": {
      "cover_asset_id": "ASSET_ID",
      "options": {"summary": "示例导语", "publish_text": "分享一篇教程"}
    }
  },
  {"platform": "qiehao", "account_id": 9},
  {"platform": "yidian", "account_id": 10, "overrides": {"cover_asset_id": "ASSET_ID"}},
  {
    "platform": "acfun",
    "account_id": 11,
    "overrides": {
      "cover_asset_id": "ASSET_ID",
      "tags": [],
      "options": {"category": "平台实际分类名称", "original": true}
    }
  },
  {
    "platform": "csdn",
    "account_id": 12,
    "overrides": {
      "cover_asset_id": "ASSET_ID",
      "tags": ["技术"],
      "options": {"summary": "介绍工具的实际使用方法。", "create_type": "原创"}
    }
  },
  {"platform": "jianshu", "account_id": 13},
  {
    "platform": "jingdong",
    "account_id": 14,
    "overrides": {
      "title": "适合京东原生文章发布的示例标题",
      "cover_asset_id": "JINGDONG_COVER_ASSET_ID",
      "options": {"category": "平台实际一级分类/平台实际二级分类/平台实际三级分类"}
    }
  },
  {
    "platform": "chejiahao",
    "account_id": 15,
    "overrides": {
      "cover_asset_id": "CHEJIAHAO_HORIZONTAL_ASSET_ID",
      "options": {
        "vertical_cover_asset_id": "CHEJIAHAO_VERTICAL_ASSET_ID",
        "agree_upload_terms": true,
        "original": false,
        "first_publish": false,
        "content_type": "非商业内容"
      }
    }
  },
  {
    "platform": "yiche",
    "account_id": 16,
    "overrides": {
      "cover_asset_id": "YICHE_HORIZONTAL_ASSET_ID",
      "options": {
        "vertical_cover_asset_id": "YICHE_VERTICAL_ASSET_ID",
        "declaration": "内容无需标注",
        "allow_forward": false,
        "allow_abstract": false
      }
    }
  },
  {
    "platform": "dongchedi",
    "account_id": 17,
    "overrides": {
      "cover_asset_id": "DONGCHEDI_HORIZONTAL_ASSET_ID",
      "options": {"vertical_cover_asset_id": "DONGCHEDI_VERTICAL_ASSET_ID"}
    }
  }
]
```

汽车平台示例中的声明和内容属性须按实际文章选择；车家号的 `agree_upload_terms:true` 仅在用户已阅读并同意对应协议时设置。各平台封面比例不同，示例使用不同素材 ID。

原稿的 `platform_options` 也可保存平台默认值：其 JSON 对象按平台名分组，每组使用与 `overrides` 相同的字段。命令 `import/update --platform-options platform-options.json` 保存默认值，某次发布的目标 `overrides` 覆盖该平台默认值。原稿正文始终保留，不自动改写。

标题、封面、话题和声明要求通过能力接口和平台实际页面共同检查。标题过长不会静默截断；一个账号检查失败，其他目标继续执行。长文章适配器按原稿顺序准备普通标题、加粗、列表、引用和正文图片；平台无法可靠保留的表格和代码块转为清晰图片，原稿仍保留可编辑内容。图片笔记遵循后面的独立转换规则。

抖音当前原生文章编辑器不接受正文超链接，会生成不支持素材提示；车家号当前 Lexical 编辑器会移除链接。两者默认遇到含超链接的任务均停止；仅当对应平台 `options.links_as_text:true` 时，将链接转为「原文字（完整网址）」供平台填写，保留原稿，转换稿记录于任务 `prepared_html`。这属于显式选择的平台格式转换，不能把没有点击链接能力的转换稿当成保留了原生链接。其余平台继续检查链接文字和目标地址，任何格式丢失都不能仅因粘贴成功而标记预览完成。

京东长文章 `jingdong` 每任务使用 1 张独立封面，素材 ID 或文件哈希与正文首图相同都会被拒绝。正文图片（包括表格、代码块转换生成的 PNG）要求宽高均至少300px、单张不超过5MiB；尺寸不足时停止为 `needs_action`，不自动放大原图。含超链接的正文仅在当前账号显示原生「超链接」工具时允许导入，缺少该控件时停止。正文通过编辑器公开 API 和正常回调导入，并同时核对可见内容与原生发布正文序列化结果；任一侧丢失文本或格式都不能继续提交。平台按账号或频道返回的动态限制和必填字段仍须在当前页面检查。

懂车号当前原生编辑器只保留一级正文标题（H1）；包含 H2–H6 的原稿会明确拒绝。可在网页编辑器中主动改为 H1 或普通段落，再保存新修订；系统不会自动合并标题层级，也不会把这些标题转成图片。原生正文去空白后最多 50000 个 UTF-16 码元，原生 HTML 最多 60000 个码元，上传后仍按实际序列化结果检查。表格与代码块仍按通用规则转换为图片并检查实际读回。

懂车号先设置用户指定的双封面，再填写标题和正文，以免平台把正文首图自动设为封面；提交前再次核对两张封面。作品同步授权窗口仅按原生关闭操作拒绝本次额外同步，不授权同步到其他平台，也不修改永久偏好。

抖音先设置封面，再填写标题和正文，避免标题引起的预览重绘与封面图层合成相互干扰。封面保存前等待真实分辨率、裁剪背景与文字两层生成图解码，完成只点一次；明确失败提示会停止，只有新的平台 CDN 封面读回才算准备成功。这一顺序已经通过本轮完整真实预览，不能替代原生话题和声明的独立验收。

微信公众号分别读取标题、作者、摘要、正文与封面。保存草稿不等于正式发布；平台要求扫码或管理员确认时仍需人工完成，控件缺失、存在歧义或无法核对结果时保留需要处理或待确认状态，不重复提交。

## 图片笔记转换

小红书、快手、视频号、京东图文、小红书商家号和淘宝光合使用「文本描述 + 有序图片」。普通段落转为描述，链接保留文字及完整网址；正文图片按原稿顺序形成图片列表。独立封面未出现在正文图片中时加到首位；已出现时不重复添加，也不改变原有图片顺序。京东图文和淘宝光合若选定的封面已在正文图片中，该图片必须是首图，否则任务停止；请调整原稿图片顺序或选择独立封面。至少需要一张正文图片或封面，图片上限包含新增封面；图片须为 JPEG 或 PNG。京东图文每图不超过 5MB，其余图片笔记平台每图不超过 20MB；淘宝光合每图宽高均至少 720px。

含标题层级、加粗、列表、引用、表格或代码等富文本结构时，必须在该平台的 `options` 显式设置 `flatten_content:true`。这会保留文字并去除富文本排版，不保留正文图片与段落的交错布局，也不把表格或代码自动渲染成图片。不开启时任务停止并提示转换要求；原稿保持不变。平台能力接口分别返回图片笔记的格式能力及转换说明。

当前使用以下保守上限，尚待真实账号逐项核实。描述上限包含完整链接网址和追加的话题文字。超限会明确拒绝，不会自动截短标题、正文或丢弃图片；页面标注的更低上限同样会阻止提交。

| 平台 | 标题上限 | 描述上限 | 图片上限 |
| --- | --- | --- | --- |
| 小红书 | 20 字 | 1000 字 | 18 张 |
| 快手 | 90 字 | 500 字，包含作为首行的标题 | 30 张 |
| 视频号 | 16 字 | 1000 字 | 9 张 |
| 京东图文 `jd` | 20 字 | 1000 字 | 20 张 |
| 小红书商家号 | 20 字 | 1000 字 | 9 张 |
| 淘宝光合 | 30 字 | 1000 字 | 9 张 |

上传完成须读回完整文本、图片数量、顺序与平台图片地址。小红书、快手、视频号、京东图文和小红书商家号的话题作为 `#话题` 普通文字追加到描述，不保证成为平台原生话题，且当前不提供创作声明选项。淘宝光合不支持非空话题，必须明确选择创作声明。未支持的声明请求会被拒绝；缺少必要控件或无法读回时返回 `needs_action`。正式提交沿用持久化后单次点击的规则。

### 京东图文、商家商品笔记与淘宝光合

京东图文 `jd` 使用[图文入口](https://dr.jd.com/n/publish-graphic.html)，首图生成的 3:4 封面须读回确认。`options.product_links` 可关联最多 10 个商品，按换行或逗号分隔 SKU 或 `https://item.jd.com/商品编号.html` 链接，总长度最多 2000 字符；适配器逐项核对关联结果。该字段通常可留空；账号或频道要求关联商品而未配置时会停止。标题采用 5–20 字，其中 20 字为当前保守上限；页面显示更严格要求时仍须满足。能登录京东账号不代表已开通图文发布权限。

小红书商家号使用[商家后台](https://ark.xiaohongshu.com/ark/home)和[商品笔记入口](https://ark.xiaohongshu.com/app-note/publish)，通过 `customer.xiaohongshu.com` 独立登录。账号须具有店铺与商品笔记权限。`options.shop_name` 填后台显示的完整店铺名称，`options.product_id` 填要关联的准确商品 ID。店铺不匹配、商品无法精确匹配或关联卡片无法核对时返回 `needs_action`。普通小红书创作者账号与商家号分别管理，不能将普通账号会话视为商家登录依据。

淘宝光合使用[光合创作者平台](https://creator.guanghe.taobao.com/)的「图文」入口，首图作为封面。素材库中只选择本任务新上传的图片，不复用同名历史素材，并核对图集地址与本次素材卡片地址一致；平台改变缩略图地址格式而无法一致核对时会停止。`options.statement` 必须明确选择「内容无需标注」「含AI生成内容」「含虚构演绎内容」「内容为转载」「个人观点，仅供参考」或「内容含营销信息」。当前不支持话题、商品关联、音乐、品牌或平台原生定时，不会自动选择这些字段；可以通过 PostSail 后端排期到点执行立即发布。

下列目标示例使用占位账号和素材 ID；请替换为服务返回值，声明按文章实际情况选择。

```json
[
  {"platform":"xiaohongshu","account_id":18,"overrides":{"options":{"flatten_content":true}}},
  {"platform":"kuaishou","account_id":19,"overrides":{"options":{"flatten_content":true}}},
  {"platform":"tencent","account_id":20,"overrides":{"options":{"flatten_content":true}}},
  {"platform":"wechat","account_id":21,"overrides":{"cover_asset_id":"WECHAT_COVER_ASSET_ID","tags":[],"options":{"author":"作者","summary":"文章摘要"}}},
  {"platform":"jd","account_id":22,"overrides":{"options":{"flatten_content":true}}},
  {"platform":"xiaohongshu_merchant","account_id":23,"overrides":{"options":{"flatten_content":true,"product_id":"实际商品ID","shop_name":"完整店铺名称"}}},
  {"platform":"taobao","account_id":24,"overrides":{"tags":[],"options":{"flatten_content":true,"statement":"内容无需标注"}}}
]
```

这些能力尚未执行真实账号预览或发布。先在网页登录对应平台，取得账号 ID，再以 `--preview` 运行目标；出现 `needs_action` 时按任务消息核对权限、店铺 / 商品、控件与读回证据。预览不会点击正式发布，但平台可能自动保存草稿。

## 提交、预览与结果确认

默认正式发布；使用 `--preview` 只准备内容和检查页面。每次正式操作建议事先确定一个唯一幂等键，并保存提交返回的批次 ID。

```bash
sau article publish ARTICLE_ID --revision 3 --targets ./targets.json --preview --idempotency-key draft-r3-preview-01 --json
sau article publish ARTICLE_ID --revision 3 --targets ./targets.json --idempotency-key draft-r3-publish-01 --json
sau article publish ARTICLE_ID --platform zhihu --account-id 3 --account-id 8 --idempotency-key draft-zhihu-01 --json
sau article status BATCH_ID --json
sau article status BATCH_ID --wait --timeout 300 --json
```

不提供 `--revision` 时先获取当前修订。不提供 `--idempotency-key` 时生成 UUID，成功或连接失败的输出都会保留实际使用的键。重放同一次请求时复用原键；原键不能用来提交不同内容。首次请求失联时应复用原键核查或查询记录，不能改用新键盲目重新提交。

任务状态如下：

| 状态 | 含义与后续动作 |
| --- | --- |
| `scheduled` | 排期已持久化，尚未到点或等待执行器；支持改期和取消 |
| `cancelled` | 用户已取消，未提交平台；不自动恢复或重试 |
| `queued` | 后端已接收任务，尚未开始；并不代表平台已发表 |
| `running` | 浏览器正在准备、校验或提交内容 |
| `needs_action` | 登录、权限、格式或选项准备失败，或平台需要人工验证；先检查 `submit_started`，再按记录允许的操作处理 |
| `previewed` | 平台预览准备与校验完成，没有正式点击发布；平台可能自动保存草稿 |
| `submitted` | 取得明确的平台接收回执，可能仍在审核；不等于已发表 |
| `published` | 取得已发表依据，记录可获取的平台链接或内容 ID |
| `failed` | 提交前或明确拒绝导致失败，可按提示安全重试 |
| `unknown` | 提交后的超时、失联或中断导致结果待确认；禁止直接再次发布 |

`status --wait` 每 2 秒查询一次，等待 `scheduled` / `queued` / `running`；全部目标都不再等待或执行时结束等待，返回预览完成、审核中、已取消、需要处理或待确认等实际状态。某个账号需要处理时，其余排队目标继续执行。等待超时退出码为 `2`，任务仍在后台执行；其他命令 API 调用成功退出 `0`，执行或 API 失败退出 `1`。命令语法错误由参数解析器输出帮助并退出 `2`。查询退出码 `0` 表示成功读到记录，需要同时检查每个任务状态。

一个任务失败只重试这个任务，继续使用原任务快照：

```bash
sau article retry TASK_ID --json
```

提交后的不确定结果必须先人工核查平台内容列表或文章页面，再记录核查依据：

```bash
sau article resolve TASK_ID --resolution published --platform-url https://example.com/article/123 --note "已核对该账号内容列表和文章页面" --json
sau article resolve TASK_ID --resolution submitted --note "平台明确显示已提交，当前审核中" --json
sau article resolve TASK_ID --resolution not_published --note "已核对平台内容列表及草稿，确认没有提交" --json
```

`resolve` 只记录结论，不执行发布。确认未发布后，需要显式调用 `retry` 才重新执行。平台未能给出明确证据时保留 `unknown`，不要把“点击过发布”当作成功。

已取得平台回执的 `submitted` 任务，也可在公开文章页面核对后使用 `resolve --resolution published`，须填写完整平台链接和核查说明。网页对应「核对公开发表」入口。该状态只能向 `published` 更新，不能降级为未发布或重新发送；内容 ID、提交标记和执行次数保留。

正式操作在第一次可能提交之前先持久化 `submit_started`。持久化失败时不点击；持久化后点击异常、页面超时或进程中断，不能通过换按钮、重开页面或循环点击重发。微博头条文章的「下一步」和最终短微博「发布」分别处理，提交边界在下一步前记录，两步各点击一次；配套微博文字填写后再次读回。抖音预览在打开编辑器前先精确阻断官方文章创建接口 `https://creator.douyin.com/web/api/media/aweme/create_v2/`（含查询参数）；封面准备完成后再安装发布按钮与快捷键保护。其他平台预览提前安装页面保护。平台自己的自动保存草稿仍可能发生。

抖音正式任务在记录提交边界之前安装被动响应监听，只读取浏览器真实产生的 `POST /web/api/media/aweme/create_v2/` 回执，不主动调用发布接口。请求必须属于 `item.common.media_type=43` 的原生文章；HTTP 2xx、响应根字段 `status_code` 为数值 `0` 且 `item_id` 为有效正整数字符串时，记录为 `submitted` 并保留内容 ID。其他状态码或未知格式继续按页面证据核对；响应解析尚未完成时等待，不重复发布。接口接收不表示审核通过，不凭内容 ID 拼接公开链接或标记 `published`。

京东长文章 `jingdong` 预览在打开文章页面前安装发布与保存草稿保护，正式提交只点击一次原生「发布」。官方“发布成功，等待审核！”属于 `submitted`，不等于公开发表；仅跳转到内容列表也可能是保存草稿，不能作为发布成功依据。账号出现验证码或提交结果不明确时不会再次点击。

## API 约定

所有 JSON 使用 `snake_case`，统一响应格式为：

```json
{"code": 200, "msg": "处理完成", "data": {"id": "ARTICLE_ID", "revision": 1}}
```

| 方法与路径 | 请求与返回 |
| --- | --- |
| `POST /api/article-assets` | multipart `file` 或 JSON `{"url":"https://..."}`；返回素材 `id` 和相对 `url` |
| `GET /api/article-assets/{id}/content` | 返回已校验的图片文件 |
| `GET /api/article-assets/{id}` / `DELETE /api/article-assets/{id}` | 查询素材公开字段 / 删除未被原稿或发布快照引用的素材 |
| `POST /api/articles` | `title,content,format,cover_asset_id,tags,platform_options`；正文格式是 `html/markdown/text` |
| `GET /api/articles` | 最近修改的原稿列表，最多 500 条；CLI 的 `--limit` 在客户端限制展示数量 |
| `GET /api/articles/{id}` | 原稿及清理后的 `content_html`、修订号 |
| `PATCH /api/articles/{id}` | 原稿字段及必须的 `expected_revision`；修订冲突拒绝更新 |
| `GET /api/article-accounts` | 已登记文章平台的已有账号，含 `id,platform,user_name,status`，不返回 Cookie 路径；CLI 在客户端按 `--platform` 筛选 |
| `GET /api/article-capabilities` | `data={"platforms":[...]}`；标题、封面、格式、`option_fields`、`permission_check`、`verification`、`scheduled` 与 `live_verified`；新增平台还公开 `available`、`reason`、`title_limit_confirmed`、`cover_supported` 等约束；`available:false` 的平台不能执行预览或发布，`type:asset` 的选项使用已上传素材 ID |
| `POST /api/articles/{id}/publish` | `revision,targets,mode,idempotency_key`；可选顶层或每目标 `schedule`；返回批次与各账号任务 |
| `GET /api/article-publish-tasks?page=1&page_size=50` | 所有原稿尚未开始的发布任务，`data={items,total,page,page_size}`；`page_size` 为 1–100，默认 50；项目后台未启动 worker 时仍可查询 |
| `PATCH /api/article-publish-tasks/{id}/schedule` | `schedule,expected_schedule_revision`；可用平台尚未开始执行的文章 / 图文任务可改期 |
| `POST /api/article-publish-tasks/{id}/cancel` | `expected_schedule_revision`；取消尚未开始执行的发布任务，不撤回平台内容 |
| `GET /api/article-publish-batches/{id}` | 批次、各账号状态、错误、截图和平台链接 |
| `GET /api/article-publish-batches?article_id={id}` | 查询某一原稿的批次记录；省略参数则查询全部近期批次 |
| `POST /api/article-publish-tasks/{id}/retry` | 安全重试原任务；待确认或已成功任务不能直接重试 |
| `POST /api/article-publish-tasks/{id}/resolve` | `resolution,platform_url,note`；记录人工核查结论 |
| `GET /api/article-publish-tasks/{id}/evidence/{filename}` | 读取该任务的截图、校验摘要等证据文件 |

文章发布请求示例：

```json
{
  "revision": 3,
  "mode": "publish",
  "idempotency_key": "draft-r3-publish-01",
  "targets": [
    {"platform": "zhihu", "account_id": 3, "overrides": {"title": "平台标题"}},
    {"platform": "sohu", "account_id": 5}
  ]
}
```

直接调用发布 API 时必须提供 `idempotency_key`，也可以通过 `Idempotency-Key` 请求头传入。正文清理后的 HTML 保存在 `content_html`；创建原稿的 `format` 默认是 `html`，CLI 根据文件自动确定格式。修改时 `expected_revision` 必须等于当前修订。排期使用本节定义的 `schedule` 对象；旧 `publish_date`、`enableTimer` 明确返回 HTTP `400`，不会静默改成立即发布。

任务结果包含 `id,status,stage,message,attempts,submit_started,retry_allowed,platform_id,platform_url,platform_status,evidence` 等公共字段，以及 `scheduled_at`（UTC，立即发布为 null）、`schedule_timezone`、`schedule_revision`、`reschedule_allowed`、`cancel_allowed`。待发布列表额外提供任务快照标题 `title`，不返回 Cookie 或内部快照。能力接口的 `scheduled` / `schedule_mode:server` 表示后端排期能力，不代表已完成真实定时发布验收。`evidence` 是该任务的服务相对链接。只有已取得平台依据才记录 `submitted` 或 `published`；自动浏览器适配器的真实账号验收仍需逐平台完成。

每个“平台 + 账号”独立保存状态，执行器串行领取任务。任务内容使用提交时的快照；原稿后续编辑不会改变它。服务重启后，排队任务继续执行；提交前中断允许安全重试，提交后中断进入 `unknown`，防止重复发表。

旧文章发布入口转接同一任务服务，响应增加批次 ID；HTTP 受理只表示任务已入队，使用批次状态查询实际结果。现有视频入口不改变。

## 存储与迁移

升级合并版本时先停止后台任务并备份数据。旧分支账号类型 `12`–`16` 可能代表不同平台，未确定归属的账号会显示「平台待确认」并暂停使用；按[账号平台迁移](./account-platform-migration.md)确认后保留原账号 ID、会话和历史记录，不要求重新建号。

SQLite 通过增量建表增加 `articles`、`article_assets`、`article_asset_refs`、`article_publish_batches`、`article_publish_tasks` 和 `article_worker_lease`，保留已有账号与视频素材。`article_asset_refs` 分别保护原稿、平台默认封面、平台选项中的竖封面和任务快照引用，不能只删除图片文件而不处理数据库引用。

默认图片和证据位于 `articleData/`（`assets/`、`evidence/`）；这些目录与 `db/database.db`、`cookiesFile/` 一起备份和迁移。备份前停止后台发布，避免正在提交的任务跨机器重复执行。素材文件按当前配置目录和素材 ID 定位，数据库保存文件名；迁移到另一目录后按新项目目录运行，或同步 Flask 的 `ARTICLE_ASSET_DIR` 等目录配置，不需要改写数据库绝对路径。必须连同素材文件迁移，不能只复制数据库。备份包含账号会话和发布内容，不能提交到公开仓库。账号 API 仅提供公共账号信息，不暴露 Cookie 内容或服务器路径。

## 验证范围

文章接入包含离线及受控浏览器验证；这些验证不能替代真实平台结果。仓库中的验证范围如下：

合并前 main 分支的 2026-10-03 完整回归开启受控浏览器测试，589 项全部通过、无跳过；另行运行的 83 项共享专项、前端生产构建、当时 21 项能力回读及网页流程检查均通过。这是合并前的验证范围；当前合并版本的回归结果单独记录于[验证记录](./article-platform-verification.md)。

| 验证层 | 实际验证内容 |
| --- | --- |
| API / CLI | 临时 SQLite、Flask 路由、模拟平台回执；原稿修订、图片保护、快照、幂等、平台注册、单账号失败、安全重试及服务中断恢复 |
| 后端排期 | 受控时钟与临时 SQLite；28 平台独立账号和执行器工厂校验、正文与素材顺序、商品和双封面选项冻结、按账号到期执行、时区及夏令时、迁移、重启恢复、到期会话失效、改期取消竞争与版本冲突；真实平台定时发布尚未执行 |
| 浏览器适配 | 本地 Chrome 受控页面；富文本粘贴、原生表格 / 代码、PNG 回退、长块分段、图片上传和错位阻止、标题 / 声明 / 话题读回、预览禁止提交 |
| 原生文章提交边界 | 受控 mock；未知平台拒绝、歧义按钮拒绝、持久化失败不点击、点击异常不重试、微博下一步 / 最终发布分别处理、默认配套微博文字读回 |
| 网页 | 隔离后端与假账号；保存刷新、正文图 / 封面、留空继承、重复点击、失败隔离、宽窄屏布局与浏览器错误检查 |
| 兼容性 | 现有视频 CLI、账号登录相关自动测试；新增账号类型、官方域名边界、正向会话证据、文章账号拒绝视频请求、京东会话和文章权限边界及旧数据保留 |
| 图片笔记与公众号 | 富文本转换显式选择、描述和图片数量 / 顺序限制、店铺与商品精确选择、声明要求、草稿与发布区分；公开源码研究与隔离浏览器检查不代表真实发布 |
| 真实平台 | 抖音完整真实预览通过：标题、正文三图顺序、完整正文、平台 CDN 图片与高清封面均已读回，`submit_started=0`；正式发布已取得明确提交回执，公开文章已现场核实。未验收真实话题或声明；其他 27 个能力缺少验收账号；京东长文章与三个汽车平台另有官方源码和离线浏览器组件回读证据，均未完成真实登录、上传或发布 |

能力接口的 `live_verified` 与 `verification.preview/submitted/published` 分别记录验收范围；实际返回值以运行版本为准，真实任务证据见验证记录。代码中存在选择器、真实编辑器打开、受控测试通过，都不能直接认定真实提交或公开发表。逐平台最新结果见[文章平台验证记录](./article-platform-verification.md)。单个平台通过不代表其余平台通过，也不代表 Windows、macOS、Linux 全部通过。[可复用验收稿](../tests/fixtures/article-acceptance/README.md)包含三张正文图片、封面、表格及代码块，标题明确标注测试用途。

离线回归命令：

```bash
python -m unittest discover -s tests -v
python -m unittest tests.test_native_articles tests.test_extended_article_accounts -v
# 可选本地 Chrome 模拟测试，仅访问受控测试页面。
# Linux / macOS：
OMNIPOST_BROWSER_TESTS=1 python -m unittest tests.test_article_adapter -v
OMNIPOST_BROWSER_TESTS=1 python -m unittest tests.test_chejiahao_articles tests.test_yiche_articles tests.test_dongchedi_articles -v
# Windows PowerShell：
$env:OMNIPOST_BROWSER_TESTS="1"; python -m unittest tests.test_article_adapter -v
```
