# 独立多平台图文发布

PostSail 接收准备好的原稿，通过同一文章任务服务向十六个平台发布图文：抖音、快手、视频号、小红书、百家号、今日头条、微博、知乎、搜狐号、微信公众号，以及 B站、企鹅号、京东、小红书商家号、懂车号、淘宝光合。抖音使用原生文章，B站使用专栏长图文，微博使用头条文章，微信公众号和企鹅号使用各自的文章创作入口；小红书、快手、视频号、京东、小红书商家号和淘宝光合使用图片笔记，正文按下文说明转换为描述和有序图片。官网沿用独立流程；文章功能不自动抓取官网，也不依赖官网发布结果。

十六个平台的代码接入与真实账号验收分别记录。2026-10-01 已现场验证抖音单篇文章的标题、完整正文、三张正文图顺序及高清封面，预览和正式提交均通过，[抖音公开文章](https://www.douyin.com/article/7691535675165871406)已独立打开核实；其余十五个平台缺少验收账号。2026-10-03 两轮扩展的小红书、快手、视频号、微信公众号、京东、小红书商家号、懂车号和淘宝光合均未执行真实账号预览或发布。抖音此前未验收真实原生话题或声明，不能据此认定全部专属选项已通过。具体过程、平台限制和证据见[文章平台验证记录](./article-platform-verification.md)。

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

十六个平台标识是 `douyin`、`kuaishou`、`tencent`、`xiaohongshu`、`baijiahao`、`toutiao`、`weibo`、`zhihu`、`sohu`、`wechat`、`bilibili`、`qiehao`、`jd`、`xiaohongshu_merchant`、`dongchedi`、`taobao`。账号 ID 使用 `accounts` 返回的 `id`，不要填 CLI 视频命令中的 `account_name`。`tencent` 是视频号，`wechat` 是微信公众号，两者分别登录并使用独立账号。小红书商家号使用 `xiaohongshu_merchant`，需独立登录商家后台；不能复用普通小红书创作者会话。

```bash
sau article accounts --json
sau article accounts --platform zhihu --json
sau article capabilities --json
```

当前文章约束如下。它们是本版本的配置限制，实际账号页面仍会检查权限和控件；平台更新后以能力接口及页面提示为准。

| 平台 | 账号类型 | 原生内容 | 标题字数 | 封面 |
| --- | --- | --- | --- | --- |
| 抖音 `douyin` | 3 | 原生文章 | 1–30 | 必填，宽高均至少 500px，≤20MB |
| 快手 `kuaishou` | 4 | 图片笔记 | 1–90，作为描述首行 | 可选，未在正文图片中时放到图片列表首位 |
| 视频号 `tencent` | 2 | 图片笔记 | 1–16 | 可选，未在正文图片中时放到图片列表首位 |
| 小红书 `xiaohongshu` | 1 | 图片笔记 | 1–20 | 可选，未在正文图片中时放到图片列表首位 |
| B站 `bilibili` | 6 | 专栏 / 长图文 | 1–30 | 可选，至少 600×336px，≤20MB |
| 百家号 `baijiahao` | 5 | 文章 | 2–64 | 必填，≤5MB |
| 今日头条 `toutiao` | 7 | 文章 | 1–30 | 可选，≤20MB |
| 微博 `weibo` | 10 | 头条文章 | 1–32 | 必填，≤10MB |
| 知乎 `zhihu` | 9 | 文章 | 1–100 | 可选，≤10MB |
| 企鹅号 `qiehao` | 11 | 文章 | 5–64 | 可选，≤10MB |
| 搜狐号 `sohu` | 8 | 文章 | 5–72 | 可选，宽高分别大于 450px 和 300px，≤10MB |
| 微信公众号 `wechat` | 12 | 公众号文章 | 1–64 | 必填，≤10MB |
| 京东 `jd` | 13 | 图片笔记 | 5–20，页面限制另行校验 | 可选，首图生成3:4封面，每图≤5MB |
| 小红书商家号 `xiaohongshu_merchant` | 14 | 商家图片笔记 | 1–20 | 可选，未在正文图片中时放到图片列表首位 |
| 懂车号 `dongchedi` | 15 | 文章 | 1–30 | 必填，≤10MB |
| 淘宝光合 `taobao` | 16 | 图片笔记 | 1–30 | 首图作为封面；每图至少720×720px，≤20MB |

封面仅接受 JPEG 或 PNG。微博、企鹅号、微信公众号分别使用类型 `10`、`11`、`12`，既有类型不改号；微信视频号仍为类型 `2`。本轮新增平台依次使用 `13`（京东）、`14`（小红书商家号）、`15`（懂车号）、`16`（淘宝光合）。微信公众号会话对应 `mp.weixin.qq.com`，不能用视频号会话替代。同一 B站账号可供视频和文章使用：视频保留 `biliup` 会话，文章读取时只在内存转换为浏览器会话。标准 Playwright `storage_state` 和 `biliup` JSON 均可通过网页导入，导入会校验结构、目标域名和实际登录状态，不能仅凭 Cookie 存在认定可发布。

`capabilities` 返回每个平台的 `option_fields`，网页据此展示专属字段，API 和 CLI 使用同一平台定义。主要选项如下：

| 平台 | `options` 字段 | 实际处理 |
| --- | --- | --- |
| 抖音 | `summary`、`links_as_text`、`statement` | 摘要最多30字；显式启用链接转文字；声明按平台原文查找 |
| B站 | `statement` | 当前编辑器未提供可配置分区；话题通过正文原生标签节点处理 |
| 百家号 | `ai_generated` | 使用原生 AI 内容声明并检查选中状态 |
| 今日头条、知乎、搜狐号 | `statement` | 仅接受能力接口列出的声明并读取选中状态 |
| 微博 | `summary`、`publish_text`、`statement` | 导语最多44字；配套微博文字留空使用文章标题 |
| 企鹅号 | `category`、`summary`、`statement` | 精确分类候选；摘要与声明必须有可核实的原生控件 |
| 小红书、快手、视频号 | `flatten_content` | 富文本转图片笔记描述需显式启用；当前不提供创作声明选项 |
| 微信公众号 | `author`、`summary` | 作者最多8字，摘要最多120字；填写后读回，当前不提供创作声明选项 |
| 京东 | `flatten_content`、`product_links` | 转换须显式启用；商品可留空，填写时以换行或逗号分隔完整京东商品 URL 或 SKU，最多10个、字段共2000字；逐项核对关联结果 |
| 小红书商家号 | `flatten_content`、`product_id`、`shop_name` | 转换须显式启用；必填该店铺的准确商品 ID 与完整店铺名称，选择后核对关联结果 |
| 懂车号 | 无 | 当前不提供话题、声明或其他专属选项；有默认话题时须通过 `tags:[]` 清空 |
| 淘宝光合 | `flatten_content`、`statement` | 转换须显式启用；声明为必选项，使用能力接口列出的6个选项；有默认话题时须通过 `tags:[]` 清空 |

文本声明字段不代表任意声明均可用：页面没有精确选项、话题候选没有成为原生选中项、封面仅是本地预览，都会停止为 `needs_action`，不会忽略该选项继续提交。企鹅号出现必填内容自主声明时，需要在平台覆盖项中指定页面显示的声明。账号已登录也可能因未实名、等级、发文额度或文章权限而无法打开编辑器；实际编辑器可用且内容完整读回后才允许继续。

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
  {"platform": "xiaohongshu", "account_id": 10, "overrides": {"options": {"flatten_content": true}}},
  {"platform": "kuaishou", "account_id": 11, "overrides": {"options": {"flatten_content": true}}},
  {"platform": "tencent", "account_id": 12, "overrides": {"options": {"flatten_content": true}}},
  {
    "platform": "wechat",
    "account_id": 13,
    "overrides": {
      "tags": [],
      "cover_asset_id": "ASSET_ID",
      "options": {"author": "示例作者", "summary": "示例公众号摘要"}
    }
  },
  {"platform": "jd", "account_id": 14, "overrides": {"options": {"flatten_content": true}}},
  {
    "platform": "xiaohongshu_merchant",
    "account_id": 15,
    "overrides": {
      "options": {
        "flatten_content": true,
        "product_id": "YOUR_PRODUCT_ID",
        "shop_name": "后台显示的完整店铺名称"
      }
    }
  },
  {
    "platform": "dongchedi",
    "account_id": 16,
    "overrides": {"tags": [], "cover_asset_id": "ASSET_ID"}
  },
  {
    "platform": "taobao",
    "account_id": 17,
    "overrides": {
      "tags": [],
      "options": {"flatten_content": true, "statement": "内容无需标注"}
    }
  }
]
```

原稿的 `platform_options` 也可保存平台默认值：其 JSON 对象按平台名分组，每组使用与 `overrides` 相同的字段。命令 `import/update --platform-options platform-options.json` 保存默认值，某次发布的目标 `overrides` 覆盖该平台默认值。原稿正文始终保留，不自动改写。

标题、封面、话题和声明要求通过能力接口和平台实际页面共同检查。标题过长不会静默截断；一个账号检查失败，其他目标继续执行。长文章适配器按原稿顺序准备普通标题、加粗、列表、引用和正文图片；无法可靠保留的表格和代码块转为清晰图片，原稿仍保留可编辑内容。图片笔记使用以下独立转换规则。

## 图片笔记转换

小红书、快手、视频号、京东、小红书商家号和淘宝光合使用「文本描述 + 有序图片」的发布形态。普通段落转为描述，链接保留文字及完整网址；正文图片按原稿顺序形成图片列表。独立封面未出现在正文图片中时加到首位；已出现时不重复添加，也不改变原有图片顺序。京东和淘宝光合若选定的封面已经存在于正文图片中，该图片必须是首图，否则任务停止；请调整原稿图片顺序或选择独立封面。至少需要一张正文图片或封面，图片上限包含新增的封面；每张图片须为 JPEG 或 PNG。京东每图不超过5MB，其余图片笔记平台每图不超过20MB；淘宝光合每图宽高均至少720px。

含标题层级、加粗、列表、引用、表格或代码等富文本结构时，必须在该平台的 `options` 显式设置 `flatten_content:true`。这会保留文字并去除富文本排版，不保留正文图片与段落的交错布局，也不把表格或代码自动渲染成图片。不开启时任务会停止并提示转换要求；原稿保持不变。平台能力接口分别返回图片笔记的格式能力及转换说明，不能将其视为长文章格式支持。

当前使用以下保守上限，尚待真实账号逐项核实。描述上限包含完整链接网址和追加的话题文字。超限会明确拒绝，不会自动截短标题、正文或丢弃图片；页面标注的更低上限同样会阻止提交。

| 平台 | 标题上限 | 描述上限 | 图片上限 |
| --- | --- | --- | --- |
| 小红书 | 20字 | 1000字 | 18张 |
| 快手 | 90字 | 500字，包含作为首行的标题 | 30张 |
| 视频号 | 16字 | 1000字 | 9张 |
| 京东 | 20字 | 1000字 | 20张 |
| 小红书商家号 | 20字 | 1000字 | 9张 |
| 淘宝光合 | 30字 | 1000字 | 9张 |

上传完成需要读回完整文本、图片数量、顺序与平台图片地址。小红书、快手、视频号、京东和小红书商家号的话题作为 `#话题` 普通文字追加到描述，不保证成为平台原生话题，且当前不提供创作声明选项。淘宝光合须清空话题并明确选择创作声明。未支持的声明请求会被拒绝。缺少必要控件或无法读回时返回 `needs_action`。正式提交沿用持久化后单次点击的规则，不复用历史图片笔记 uploader 的循环发布流程。

## 京东、小红书商家号、懂车号与淘宝光合

京东使用[京东内容开放平台图文入口](https://dr.jd.com/n/publish-graphic.html)，内容按上面的图片笔记规则转换，至少需要一张图片；首图生成的3:4封面需要读回确认。可通过 `options.product_links` 关联最多10个商品，按换行或逗号分隔完整京东商品 URL 或 SKU，适配器逐项核对关联结果。该字段通常可留空；账号或频道要求关联商品而未配置时，任务会停止。标题采用5–20字范围，其中20字是当前保守上限，页面显示的更严格要求仍需满足。能登录京东账号不代表已开通内容发布权限；请先确认该账号能打开图文编辑器，再运行预览。

小红书商家号使用[商家后台](https://ark.xiaohongshu.com/ark/home)和[商品笔记入口](https://ark.xiaohongshu.com/app-note/publish)，通过 `customer.xiaohongshu.com` 独立登录。账号须具有店铺与商品笔记权限。填写 `options.shop_name` 为后台显示的完整店铺名称，`options.product_id` 为要关联的准确商品 ID；不会自动选取第一个商品。店铺不匹配、商品无法精确匹配或关联卡片无法核对时，任务会停止为 `needs_action`。商品 ID 最多64字，店铺名称最多100字；图片采用9张保守限制，尚未确认官方上限。普通小红书创作者账号与商家号分别管理。

懂车号使用[文章入口](https://mp.dcdapp.com/profile_v2/publish/article)，按原生长文章准备正文和图片。当前采用标题30字、封面必填且不超过10MB的保守限制。当前不提供原生话题或声明；原稿含话题时，在该账号配置中选择「清空话题」或传入 `overrides.tags:[]`。提交前仍需核对账号文章权限、完整正文、图片顺序和封面，不能以打开后台认定准备完成。

淘宝光合使用[光合创作者平台](https://creator.guanghe.taobao.com/)中的「图文」入口。至少需要一张图片，最多9张，每张至少720×720px且不超过20MB，首图作为封面；平台素材库中只选择本任务新上传的图片，不复用同名历史素材，并核对图集地址与本次素材卡片地址一致；平台改变缩略图地址格式而无法一致核对时会停止。`options.statement` 必须明确选择「内容无需标注」「含AI生成内容」「含虚构演绎内容」「内容为转载」「个人观点，仅供参考」或「内容含营销信息」，按内容实际情况选择。当前不支持话题、商品关联、音乐、品牌或定时发布，不会自动选择这些字段。示例中的声明仅用于展示参数，请按实际内容替换。

以上新增平台尚未执行真实账号预览或发布。先在网页登录对应平台，使用 `sau article accounts --json` 取得账号 ID，再以 `--preview` 运行目标；出现 `needs_action` 时按任务消息检查权限、店铺 / 商品、控件与读回证据。预览不会点击正式发布，但平台可能自动保存草稿。通过预览后，正式提交仍需取得明确平台回执，公开发表需另外核对实际页面。

## 原生文章格式与封面

抖音当前原生文章编辑器不接受正文超链接，会生成不支持素材提示。默认含超链接的任务明确停止；仅当平台 `options.links_as_text:true` 时，将链接转为「原文字（完整网址）」供平台填写，保留原稿，转换稿记录于任务 `prepared_html`。这属于显式选择的平台格式转换，不能把没有点击链接能力的转换稿当成保留了原生链接。其余长文章平台继续检查链接文字和目标地址，任何格式丢失都不能仅因粘贴成功而标记预览完成。

抖音先设置封面，再填写标题和正文，避免标题引起的预览重绘与封面图层合成相互干扰。封面保存前等待真实分辨率、裁剪背景与文字两层生成图解码，完成只点一次；明确失败提示会停止，只有新的平台 CDN 封面读回才算准备成功。这一顺序已经通过本轮完整真实预览，不能替代原生话题和声明的独立验收。

微信公众号分别读取标题、作者、摘要、正文与封面。当前不支持原生话题；原稿含默认话题时，须在公众号账号设置中选择「清空话题」，或通过目标覆盖项传入 `tags:[]`。保存草稿不等于正式发布；平台要求扫码或管理员确认时仍需人工完成，控件缺失、存在歧义或无法核对结果时保留需要处理或待确认状态，不重复提交。

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
| `needs_action` | 登录、权限、格式或选项准备失败，或平台需要人工验证；先检查 `submit_started`，再按记录允许的操作处理 |
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

已取得平台回执的 `submitted` 任务，也可在公开文章页面核对后使用 `resolve --resolution published`，须填写完整平台链接和核查说明。网页对应「核对公开发表」入口。该状态只能向 `published` 更新，不能降级为未发布或重新发送；内容 ID、提交标记和执行次数保留。

正式操作在第一次可能提交之前先持久化 `submit_started`。持久化失败时不点击；持久化后点击异常、页面超时或进程中断，不能通过换按钮、重开页面或循环点击重发。微博头条文章的「下一步」和最终短微博「发布」分别处理，提交边界在下一步前记录，两步各点击一次；配套微博文字填写后再次读回。抖音预览在打开编辑器前先精确阻断官方文章创建接口 `https://creator.douyin.com/web/api/media/aweme/create_v2/`（含查询参数）；封面准备完成后再安装发布按钮与快捷键保护。其他平台预览提前安装页面保护。平台自己的自动保存草稿仍可能发生。

抖音正式任务在记录提交边界之前安装被动响应监听，只读取浏览器真实产生的 `POST /web/api/media/aweme/create_v2/` 回执，不主动调用发布接口。请求必须属于 `item.common.media_type=43` 的原生文章；HTTP 2xx、响应根字段 `status_code` 为数值 `0` 且 `item_id` 为有效正整数字符串时，记录为 `submitted` 并保留内容 ID。其他状态码或未知格式继续按页面证据核对；响应解析尚未完成时等待，不重复发布。接口接收不表示审核通过，不凭内容 ID 拼接公开链接或标记 `published`。

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
| `GET /api/article-accounts` | 十六个平台的已有账号，含 `id,platform,user_name,status`，不返回 Cookie 路径；CLI 在客户端按 `--platform` 筛选 |
| `GET /api/article-capabilities` | `data={"platforms":[...]}`；标题、封面、格式、`option_fields`、`permission_check`、`verification`、`scheduled` 与 `live_verified` |
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

仓库已有离线及受控浏览器验证；这些验证不能替代真实平台结果。2026-10-03 两轮扩展的八个平台仍需真实账号验收，不能用其他平台的测试或抖音现场记录代替。仓库中的验证范围如下：

| 验证层 | 实际验证内容 |
| --- | --- |
| API / CLI | 临时 SQLite、Flask 路由、模拟平台回执；原稿修订、图片保护、快照、幂等、平台注册、单账号失败、安全重试及服务中断恢复 |
| 浏览器适配 | 本地 Chrome 受控页面；富文本粘贴、原生表格 / 代码、PNG 回退、长块分段、图片上传和错位阻止、标题 / 声明 / 话题读回、预览禁止提交 |
| 原生文章提交边界 | 受控 mock；未知平台拒绝、歧义按钮拒绝、持久化失败不点击、点击异常不重试、微博下一步 / 最终发布分别处理、默认配套微博文字读回 |
| 网页 | 隔离后端与假账号；保存刷新、正文图 / 封面、留空继承、重复点击、失败隔离、宽窄屏布局与浏览器错误检查 |
| 兼容性 | 现有视频 CLI、账号登录相关自动测试；已有账号和视频素材表增量升级后保留 |
| 真实平台 | 抖音完整真实预览通过：标题、正文三图顺序、完整正文、平台 CDN 图片与高清封面均已读回，`submit_started=0`；正式发布已取得明确提交回执，公开文章已现场核实。未验收真实话题或声明；其他十五个平台缺少验收账号，包括两轮新增的小红书、快手、视频号、微信公众号、京东、小红书商家号、懂车号和淘宝光合 |

能力接口的 `live_verified` 与 `verification.preview/submitted/published` 分别记录验收范围；实际返回值以运行版本为准，真实任务证据见验证记录。代码中存在选择器、真实编辑器打开、受控测试通过，都不能直接认定真实提交或公开发表。逐平台最新结果见[文章平台验证记录](./article-platform-verification.md)。单个平台通过不代表其余平台通过，也不代表 Windows、macOS、Linux 全部通过。[可复用验收稿](../tests/fixtures/article-acceptance/README.md)包含三张正文图片、封面、表格及代码块，标题明确标注测试用途。

离线回归命令：

```bash
python -m unittest discover -s tests -v
python -m unittest tests.test_native_articles -v
# 可选本地 Chrome 模拟测试，仅访问受控测试页面。
# Linux / macOS：
OMNIPOST_BROWSER_TESTS=1 python -m unittest tests.test_article_adapter -v
# Windows PowerShell：
$env:OMNIPOST_BROWSER_TESTS="1"; python -m unittest tests.test_article_adapter -v
```
