# 独立多平台文章发布

PostSail 接收准备好的原稿，向百家号、知乎、今日头条、搜狐号分别发布。官网沿用自己的独立发布流程；本功能不抓取官网文章，不依赖官网发布结果。

文章发布使用 Web 后端保存的账号 ID。现有视频 CLI 的账号文件和参数保持不变。先在网页完成目标平台登录，再运行 `sau article accounts --json` 查找可用账号。第一版仅支持立即发布，定时请求会被拒绝，不会回退成立即发布。

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

四个平台标识是 `baijiahao`、`zhihu`、`toutiao`、`sohu`。账号 ID 使用 `accounts` 返回的 `id`，不要填 CLI 视频命令中的 `account_name`。

```bash
sau article accounts --json
sau article accounts --platform zhihu --json
sau article capabilities --json
```

文章、素材、批次和任务的 ID 是不透明字符串（当前为 32 位 UUID 十六进制值），账号 ID 和修订号是正整数。命令示例中的 `ARTICLE_ID`、`BATCH_ID`、`TASK_ID`、`ASSET_ID` 均替换为服务返回的实际值。

多个平台推荐使用目标文件。以下 `targets.json` 中的账号和素材 ID 是占位示例，使用前替换为服务实际返回的 ID。

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
  {"platform": "sohu", "account_id": 5}
]
```

原稿的 `platform_options` 也可保存平台默认值：其 JSON 对象按平台名分组，每组使用与 `overrides` 相同的字段。命令 `import/update --platform-options platform-options.json` 保存默认值，某次发布的目标 `overrides` 覆盖该平台默认值。原稿正文始终保留，不自动改写。

标题、封面、话题和声明要求通过能力接口和平台实际页面共同检查。标题过长不会静默截断；一个账号检查失败，其他目标继续执行。普通标题、加粗、列表、引用、链接、正文图片按原稿顺序发布；平台无法可靠保留的表格和代码块转为清晰图片，原稿仍保留可编辑内容。

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
| `queued` | 后端已接收任务，尚未开始；并不代表平台已发表 |
| `running` | 浏览器正在准备、校验或提交内容 |
| `needs_action` | 登录失效、验证码等需要人工处理；处理后重试对应任务 |
| `previewed` | 平台预览准备与校验完成，没有正式点击发布；平台可能自动保存草稿 |
| `submitted` | 取得明确的平台接收回执，可能仍在审核；不等于已发表 |
| `published` | 取得已发表依据，记录可获取的平台链接或内容 ID |
| `failed` | 提交前或明确拒绝导致失败，可按提示安全重试 |
| `unknown` | 提交后的超时、失联或中断导致结果待确认；禁止直接再次发布 |

`status --wait` 每 2 秒查询一次，只等待 `queued` / `running`；全部目标都不再排队和执行时结束等待，返回预览完成、审核中、需要处理或待确认等实际状态。某个账号需要处理时，其余排队目标继续执行。等待超时退出码为 `2`，任务仍在后台执行；其他命令 API 调用成功退出 `0`，执行或 API 失败退出 `1`。命令语法错误由参数解析器输出帮助并退出 `2`。查询退出码 `0` 表示成功读到记录，需要同时检查每个任务状态。

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
| `GET /api/article-accounts` | 四个平台的已有账号，含 `id,platform,user_name,status`，不返回 Cookie 路径；CLI 在客户端按 `--platform` 筛选 |
| `GET /api/article-capabilities` | `data={"platforms":[...]}`；平台标题、封面、支持格式与限制，首版均含 `scheduled:false,live_verified:false` |
| `POST /api/articles/{id}/publish` | `revision,targets,mode,idempotency_key`；返回批次与各账号任务 |
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

直接调用发布 API 时必须提供 `idempotency_key`，也可以通过 `Idempotency-Key` 请求头传入。正文清理后的 HTML 保存在 `content_html`；创建原稿的 `format` 默认是 `html`，CLI 根据文件自动确定格式。修改时 `expected_revision` 必须等于当前修订。发布时非零或非空的 `schedule`、`publish_date`、`enableTimer` 明确返回 HTTP `400`；不支持静默改成立即发布。

任务结果包含 `id,status,stage,message,attempts,submit_started,retry_allowed,platform_id,platform_url,platform_status,evidence` 等公共字段。`evidence` 是该任务的服务相对链接。只有已取得平台依据才记录 `submitted` 或 `published`；自动浏览器适配器的真实账号验收仍需逐平台完成。

每个“平台 + 账号”独立保存状态，执行器串行领取任务。任务内容使用提交时的快照；原稿后续编辑不会改变它。服务重启后，排队任务继续执行；提交前中断允许安全重试，提交后中断进入 `unknown`，防止重复发表。

旧文章发布入口转接同一任务服务，响应增加批次 ID；HTTP 受理只表示任务已入队，使用批次状态查询实际结果。现有视频入口不改变。

## 存储与迁移

SQLite 通过增量建表增加 `articles`、`article_assets`、`article_asset_refs`、`article_publish_batches`、`article_publish_tasks` 和 `article_worker_lease`，保留已有账号与视频素材。`article_asset_refs` 分别保护原稿、平台默认封面和任务快照引用，不能只删除图片文件而不处理数据库引用。

默认图片和证据位于 `articleData/`（`assets/`、`evidence/`）；这些目录与 `db/database.db`、`cookiesFile/` 一起备份和迁移。备份前停止后台发布，避免正在提交的任务跨机器重复执行。素材文件按当前配置目录和素材 ID 定位，数据库保存文件名；迁移到另一目录后按新项目目录运行，或同步 Flask 的 `ARTICLE_ASSET_DIR` 等目录配置，不需要改写数据库绝对路径。必须连同素材文件迁移，不能只复制数据库。备份包含账号会话和发布内容，不能提交到公开仓库。账号 API 仅提供公共账号信息，不暴露 Cookie 内容或服务器路径。

## 验证范围

本次在 macOS 上验证了以下范围：

| 验证层 | 实际验证内容 |
| --- | --- |
| API / CLI | 临时 SQLite、真实 Flask 路由、模拟四平台回执；原稿修订、图片保护、快照、幂等、单账号失败、安全重试及服务中断恢复 |
| 浏览器适配 | 本地 Chrome 受控页面；富文本粘贴、原生表格 / 代码、PNG 回退、长块分段、图片上传和错位阻止、标题 / 声明 / 话题读回、预览禁止提交 |
| 网页 | 隔离后端与假账号；保存刷新、正文图 / 封面、留空继承、重复点击、失败隔离、宽窄屏布局与浏览器错误检查 |
| 兼容性 | 现有视频 CLI、账号登录相关自动测试；已有账号和视频素材表增量升级后保留 |
| 真实平台 | 百家号、知乎、头条、搜狐均未使用真实账号预览或正式发布 |

四个平台首版能力均明确标记 `live_verified:false`，真实账号预览、审核回执和正式发表需要按实际账号逐项验收，单个平台通过不代表其余平台通过，也不代表 Windows、macOS、Linux 全部通过。[可复用验收稿](../tests/fixtures/article-acceptance/README.md)包含三张正文图片、封面、表格及代码块，标题明确标注测试用途。

离线回归命令：

```bash
python -m unittest discover -s tests -v
# 可选本地 Chrome 模拟测试，仅访问受控测试页面。
# Linux / macOS：
OMNIPOST_BROWSER_TESTS=1 python -m unittest tests.test_article_adapter -v
# Windows PowerShell：
$env:OMNIPOST_BROWSER_TESTS="1"; python -m unittest tests.test_article_adapter -v
```
