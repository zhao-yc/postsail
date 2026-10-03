# 图文平台验证记录

本记录区分代码实现、真实预览、平台接收回执和正式发表。当前十六个平台已注册到同一文章任务服务，包含原生文章和图片笔记两种形态。抖音完整真实预览已通过；其正式发布已取得官方文章创建成功回执及内容 ID，公开文章已现场核实。代码能力与真实验收分别记录，使用者仍需在自己的账号上验证实际流程。

## 本轮真实验证状态

记录日期：2026-10-01。仅有抖音验收账号；公开原稿为官网文章编号 927，包含三张正文图片。原稿和素材先导入 PostSail，官网发布流程仍独立。本次抖音验收限定为一篇文章的标题、完整正文、三张正文图及顺序、平台 CDN 地址和高清封面；原生话题、声明、其他账号和其他操作系统未验收。公开地址来自平台管理页分享字段和浏览器真实重定向，并非根据内容 ID 推测。

扩展记录：2026-10-03 新增小红书、快手、视频号与微信公众号的代码接入，未取得真实验收账号，也未执行真实预览或发布。同日第二轮新增京东、小红书商家号、懂车号、淘宝光合，也未执行真实账号预览或发布。下面保留 2026-10-01 的抖音原记录；新增平台的页面依据与保守限制见后文。

| 平台 | 原生内容 | 编辑器与素材准备 | `previewed` | `submitted` | `published` |
| --- | --- | --- | --- | --- | --- |
| 抖音 | 原生文章 | 标题、完整正文、三图顺序与平台 CDN 地址、高清封面均读回通过 | 已通过 | 已取得官方成功回执及内容 ID | 已现场核实公开文章 |
| 快手 | 图片笔记 | 已接入准备与读回流程，缺少真实验收账号 | 未验证 | 未执行 | 未执行 |
| 视频号 | 图片笔记 | 已接入准备与读回流程，缺少真实验收账号 | 未验证 | 未执行 | 未执行 |
| 小红书 | 图片笔记 | 已接入准备与读回流程，缺少真实验收账号 | 未验证 | 未执行 | 未执行 |
| B站 | 专栏 / 长图文 | 缺少真实验收账号 | 未验证 | 未执行 | 未执行 |
| 百家号 | 文章 | 缺少真实验收账号 | 未验证 | 未执行 | 未执行 |
| 今日头条 | 文章 | 缺少真实验收账号 | 未验证 | 未执行 | 未执行 |
| 微博 | 头条文章 | 缺少真实验收账号 | 未验证 | 未执行 | 未执行 |
| 知乎 | 文章 | 缺少真实验收账号 | 未验证 | 未执行 | 未执行 |
| 企鹅号 | 文章 | 缺少真实验收账号 | 未验证 | 未执行 | 未执行 |
| 搜狐号 | 文章 | 缺少真实验收账号 | 未验证 | 未执行 | 未执行 |
| 微信公众号 | 公众号文章 | 已接入准备与读回流程，缺少真实验收账号 | 未验证 | 未执行 | 未执行 |
| 京东 | 图片笔记 | 已接入准备与读回流程，缺少真实验收账号 | 未验证 | 未执行 | 未执行 |
| 小红书商家号 | 商家图片笔记 | 已接入独立店铺 / 商品核对与准备流程，缺少真实验收账号 | 未验证 | 未执行 | 未执行 |
| 懂车号 | 文章 | 已接入准备与读回流程，缺少真实验收账号 | 未验证 | 未执行 | 未执行 |
| 淘宝光合 | 图片笔记 | 已接入素材库上传、声明选择与准备读回流程，缺少真实验收账号 | 未验证 | 未执行 | 未执行 |

抖音真实页面已核实标题上限30字、摘要上限30字、正文上限20000字、正文图片上限30张、原生话题最多5个，以及封面宽高均至少500px。初始封面为322×520px，平台明确拒绝低分辨率；不能把触发文件选择器算作封面设置成功。

正文预览失败已定位到超链接：平台将链接转换为 `span[data-dy-warning]`，追加「该文本类型暂不支持，请替换素材」，其余正文读回一致。新增 `options.links_as_text`，默认关闭；用户显式开启后，将链接转换为「原文字（完整网址）」，保留原稿与完整网址，并保存任务转换稿。本次显式开启该配置后，完整正文和三张图片的相邻段落、顺序及平台地址已通过读回，高清封面也已保存并读回，最终预览任务的 `submit_started=0`。此次没有真实原生话题与声明的验收证据，其他选项不能由正文、封面通过推定成功。

封面准备改为先于标题与正文，等待裁剪背景和文字两层生成图解码后单次点击「完成」，再核对新的平台 CDN 封面。独立封面保存与完整文章预览均已取得成功证据；此前仅看到分辨率或原始图片，不能证明平台已完成封面图层合成与保存。

随后进行一次正式提交，接口回执阶段任务记录 `status=submitted`、`submit_started=1`、`attempts=1`。官方文章创建响应返回有效内容 ID，页面同时出现真实「发布成功」提示。随后从管理页实际返回的分享地址打开公开文章，使用未加载验收账号会话的浏览器核对，真实重定向到[抖音公开文章](https://www.douyin.com/article/7691535675165871406)，页面显示正确短标题、日期与完整正文。本轮 `previewed`、`submitted`、`published` 三个层次均已取得现场依据。

## 各状态的证据门槛

| 层次 | 必须取得的依据 | 不能作为依据的情况 |
| --- | --- | --- |
| 代码接入 | 平台注册、专属入口、选项处理和回归用例存在 | 仅新增下拉选项或平台名称 |
| 账号会话有效 | 会话结构与目标域名校验，平台返回正向登录依据 | Cookie 键存在、文件存在、URL 没有报错 |
| 图文权限可用 | 能打开该账号所选内容形态的编辑器并定位可编辑字段 | 仅登录视频后台，或把图片笔记误作长文章编辑器 |
| `previewed` | 标题、正文、所选形态的排版、图片数量 / 顺序 / 平台地址、封面与原生选项完整读回，并保存准备证据；图片笔记还须满足显式转换规则 | 粘贴操作成功、仅截图、已打开编辑器、平台自动保存草稿 |
| `submitted` | 取得严格匹配本次文章请求的成功响应，或编辑器外出现明确的发布 / 接收 / 审核回执 | 点击过按钮、管理页跳转、正文出现「发布成功」文字 |
| `published` | 已打开可核实的公开文章地址，正文页面含预期标题，并记录内容 ID / URL | 单纯发布成功提示、仍处于审核、列表链接未经核对 |

API 返回 `verification.preview/submitted/published` 分别表示真实验收层次，不能用一项替代另外两项。能力字段以运行版本的实际返回为准；每个发布任务另外保存自己的实际状态与证据。更新全局能力字段应对应可复查的逐平台验收记录，不能用抖音单次正文与封面预览宣称所有话题、声明或其他账号均已验收。

## 原生入口与实现依据

| 平台 | 入口 / 依据 | 目前限制 |
| --- | --- | --- |
| 抖音 | [原生文章创作入口](https://creator.douyin.com/creator-micro/content/post/article)；真实账号 DOM 与官方公开微前端脚本 | 正文超链接需显式转换；封面和原生话题均需读回 |
| 小红书 | [图片笔记入口](https://creator.xiaohongshu.com/publish/publish?from=homepage&target=image)；[上游 XiaoHongShuNote](https://github.com/dreammis/social-auto-upload/blob/0012d2c355f88f683cc38dde2a2db209e14091bc/uploader/xiaohongshu_uploader/main.py) 的图片输入与标题 / 描述控件 | 图片列表加描述；富文本转换须显式启用，缺账号尚未验收 |
| 快手 | [创作者发布入口](https://cp.kuaishou.com/article/publish/video)切换「图文」；[上游 KSNote](https://github.com/dreammis/social-auto-upload/blob/0012d2c355f88f683cc38dde2a2db209e14091bc/uploader/ks_uploader/main.py) 的图文标签、上传图片与描述控件 | 标题并入描述首行；缺账号尚未验收，不复用上游循环点击发布逻辑 |
| 视频号 | [视频号助手发布入口](https://channels.weixin.qq.com/platform/post/create)；[公开维护者源码](https://github.com/3441293738/creatorhub/blob/c588dd58e67dc7feed01d175edfd295e59e8f647/app/platforms/channels/publish.py)描述跨 iframe 的「图文」→「发表图文」路径及描述 / 短标题控件 | 公开源码标注实验性；本次无法访问官方页面核对，需真实账号校准。不能以进入视频发布页证明图文权限 |
| B站 | [当前专栏编辑器](https://member.bilibili.com/york/read-editor)；官方公开编辑器脚本 | 当前适配标题最多30字；旧专栏入口已下线；当前编辑器没有可配置分类 |
| 微博 | [头条文章编辑器](https://card.weibo.com/article/v3/editor)；[微博长文官方 PC 教程](https://www.weibo.com/ttarticle/p/show?id=2309404803154729631808)；[公开维护者浏览器脚本](https://github.com/jimliu/baoyu-skills/blob/main/skills/baoyu-post-to-weibo/scripts/weibo-article.ts) | 「下一步」与最终短微博「发布」分开处理；原生话题没有确切控件证据时要求人工处理 |
| 企鹅号 | [文章创作入口](https://om.qq.com/main/creation/article)；[近期维护者源码](https://github.com/liuxucai/qq-publish-skill/blob/master/scripts/publish_isob.js)；[维护者流程记录](https://github.com/liuxucai/qq-publish-skill/blob/master/references/workflow.md)；[文章适配器参考](https://github.com/yjmm10/MediaSync/blob/master/packages/core/src/adapters/platforms/qiehao.ts) | 新编辑器标题 / ProseMirror 优先，旧 UEditor 兼容；封面、分类、摘要、自主声明和标签须实际控件命中与读回；缺账号尚未验收 |
| 微信公众号 | [公众号后台](https://mp.weixin.qq.com/)；[公开编辑器脚本](https://github.com/jimliu/baoyu-skills/blob/main/skills/baoyu-post-to-wechat/scripts/wechat-article.ts)的 `.rich_media_content .ProseMirror`、标题 / 作者 / 摘要控件；[入口与草稿适配参考](https://github.com/yjmm10/MediaSync/blob/master/packages/core/src/adapters/platforms/weixin.ts)；[发表确认控件参考](https://github.com/Marshall-Jimmy/wechat-auto-publisher/blob/main/core/wechat_publisher.py) | `#js_submit` 与 `operate_appmsg sub=create` 只保存草稿，不算正式发布；发表扫码需人工确认，缺账号尚未验收 |
| 京东 | [图文入口](https://dr.jd.com/n/publish-graphic.html)；官方公开脚本[图文创建](https://storage.360buyimg.com/ifloors/talent-platform-new/1790145277602/assets/index-CfC4YrbB.js)、[标题 / 封面 / 商品抽屉](https://storage.360buyimg.com/ifloors/talent-platform-new/1790145277602/assets/index-DkYQO5-I.js)、[关联挂件](https://storage.360buyimg.com/ifloors/talent-platform-new/1790145277602/assets/index-D0qBDxJW.js)、[上传与账号信息](https://storage.360buyimg.com/ifloors/talent-platform-new/1790145277602/assets/main-Buzi2ykr.js) | 与文章入口分开；每图≤5MB，首图生成3:4封面需核验；商品最多10个，账号或频道另有必填要求时停止；缺账号尚未验收 |
| 小红书商家号 | [商家登录](https://customer.xiaohongshu.com/login?service=https://ark.xiaohongshu.com/ark/home)、[商品笔记入口](https://ark.xiaohongshu.com/app-note/publish)；[固定版本公开浏览器流程](https://github.com/gaoming714/ByteScript/blob/c9f8d46a4e453f83d9c1e5a9b8b135fb53b4244b/xiaohongshu0x01.py)中的店铺、商品和手动创作图文路径 | 独立商家会话；必填准确商品 ID 和完整店铺名；9张图片为保守限制。缺少店铺或商品关联读回即停止；缺账号尚未验收 |
| 懂车号 | [原生文章入口](https://mp.dcdapp.com/profile_v2/publish/article)；固定版本[公开文章适配器](https://github.com/leaperone/MultiPost-Extension/blob/6269ab4ada1cf661a3624b2b9f496bb032a391d5/src/sync/article/dongchedi.ts)及[入口注册](https://github.com/leaperone/MultiPost-Extension/blob/6269ab4ada1cf661a3624b2b9f496bb032a391d5/src/sync/article.ts) | 上游标注实验性，仅作为标题、正文和封面控件线索；当前标题30字、必填封面≤10MB为保守限制；缺账号尚未验收 |
| 淘宝光合 | [光合后台](https://creator.guanghe.taobao.com/)；固定版本[图文与素材库流程](https://github.com/Jiarenzaigusu/multi-platform-auto-upload-main-DAM-newest/blob/753566cefe5d0e3319fe52d34f3bb5485d740c08/uploader/tmall_article_uploader/main.py)、[图片 / 封面限制参考](https://github.com/yixiaoer888/yixiaoer-skill/blob/a2722c6095f57abf2e345dca637bdded44fa34df/skills/yixiaoer/references/platforms/imageText/taobaoguanghe.md)、[声明选项参考](https://github.com/DevilJie/social-auto-upload-web-ui/blob/8e33adf0e461ecbc992be244f241c6590adc608f/backend/impl/taobao_guanghe/platform.py) | [完整图文入口](https://creator.guanghe.taobao.com/page/pubNew/pic?pub_url=https%3A%2F%2Fhuodong.taobao.com%2Fwow%2Fz%2Fguang%2Fgg_publish%2Fgg-picture%3Fugc_scene%3Dpc_newcreator_pic%26pageType%3Darticle%26site%3Dguangguang&pub_scene=gg)包含 iframe 路径 `/gg_publish/gg-picture`；素材库只选择本次上传的唯一文件名；必选声明；缺账号尚未验收 |
| 百家号、知乎、今日头条、搜狐号 | 现有独立文章 uploader，经统一准备与结果读取流程接入 | 缺账号尚未验收；声明、封面与话题失败会阻止提交 |

引用公开源码用于确认入口与控件，并不代表当前用户已经登录、该账号具有文章权限或本项目已经发布成功。公开脚本中以 DOM 修改、盲选第一个按钮或管理页跳转认定成功的做法，不作为本项目结果判定依据。

## 第一轮新增平台的转换与验收范围

小红书、快手、视频号采用「文本描述 + 有序图片」。普通段落直接形成描述，链接保留文字与完整网址；含标题层级、加粗、列表、引用、表格或代码等富文本结构时，须显式设置 `options.flatten_content:true`。转换保留文字，去除富文本样式和图片与段落的交错布局，不把表格或代码改为图片。原稿不变。正文图片保留原始顺序；封面不在正文图片列表中时才加到首位，已存在的封面不重复添加或调序。

本版本采用保守上限：小红书标题20字、描述1000字、18张图片；快手标题90字、描述500字、30张图片；视频号短标题16字、描述1000字、9张图片。快手标题作为描述首行计入描述上限，图片上限包含额外前置的封面。超限停止，不自动截断。这些限制尚未在真实账号上验收，当前页面有更低上限时仍须停止。

微信公众号使用独立 `wechat` 平台和账号类型 `12`；视频号继续使用 `tencent` / 类型 `2`。公众号标题上限64字、作者8字、摘要120字，封面必填；登录凭据须属于 `mp.weixin.qq.com`。页面权限、封面裁剪、正文图片上传以及最终发布确认仍需真实账号逐项验收。扫码确认、审核中、草稿保存或管理页跳转都不能替代正式发表证据。

新增四平台的 `verification.preview/submitted/published` 均保持 `false`。离线测试用于检查内容转换、上限、图片顺序和提交边界；公开源码与离线结果都不能证明当前平台已接收或公开发表。三个图片笔记平台仅把话题作为 `#文字` 追加到描述并计入字数，不保证原生话题关联；四个新增平台当前不提供创作声明选项。缺少必要控件或读回证据时应停止为 `needs_action`。

## 第二轮新增平台的转换与验收范围

京东、小红书商家号、懂车号、淘宝光合分别使用 `jd` / 类型 `13`、`xiaohongshu_merchant` / 类型 `14`、`dongchedi` / 类型 `15`、`taobao` / 类型 `16`。既有账号类型不改号，登录与权限分别检查。四个平台的 `verification.preview/submitted/published` 均保持 `false`；本轮没有使用真实账号，也没有向这些平台执行正式提交。

京东、小红书商家号和淘宝光合使用图片笔记转换规则，富文本必须显式启用 `flatten_content`。京东当前限制标题5–20字、描述1000字、20张图片，每图不超过5MB，首图生成3:4封面后核验；选定封面若已在正文图片中却不是首图则停止，避免平台采用不同封面。小红书商家号采用标题20字、描述1000字、9张图片的保守限制。上传和读回必须核对完整文本、有序图片与平台地址；选了文件或本地预览不是上传完成证据。

京东的20字标题是当前适配的保守上限；官方通用组件包含5–27字校验且可被页面覆盖，因此实际页面的最短标题与更严格上限仍需核对。`product_links` 接受最多10个完整京东商品 URL 或 SKU，逐项核对，不默认关联商品。官方 `articleSaveImageTextDraft` 是草稿保存，不能当成 `articlePublishImageText` 正式提交；这些公开脚本依据不代表本项目已在真实账号上发布。

小红书商家号必须提供 `product_id`（准确商品 ID，最多64字）和 `shop_name`（后台完整店铺名，最多100字），使用商家入口独立登录并核对当前店铺、关联商品。公开流程只能帮助定位控件；不据此证明当前账号具有店铺权限。店铺不匹配、商品或关联结果不明确时停止为 `needs_action`，不自动选取第一个商品。

懂车号使用原生长文章，标题30字和必填封面不超过10MB是当前适配的保守限制，尚待真实账号确认。当前没有原生话题或声明支持；原稿含话题时须显式清空，不能当作选项已生效继续提交。

淘宝光合当前限制标题30字、正文1000字、1–9张图片，每图至少720×720px且不超过20MB；首图作为封面；选定封面若已存在于正文图片中却不是首图，则停止并要求调整，不能静默重排。通过图文 iframe 打开素材库，以唯一临时文件名核对本次上传的图片，保留数量和顺序证据；图集 URL 必须与本次素材卡片 URL 一致，平台改变缩略图地址形式时会保守停止。声明必须显式选择能力接口列出的6个选项之一，且核对页面选中状态；话题、商品、音乐、品牌与定时发布当前不支持。这些规则来自公开维护者代码与文档，本轮仅做源码核对和离线受控验证，未确认真实平台当前页面。

首次验收先登录目标后台确认权限，再运行 `sau article publish ... --preview` 检查任务的准备证据和 `submit_started=0`。图片笔记检查转换后的描述、图片数量与顺序；商家号另外核对店铺与关联商品；长文章检查相邻段落与正文图片顺序。预览成功后才能据实际正式任务记录提交与公开发表层次，逐平台更新本页。

## 提交安全与后续验收

正式操作先持久化 `submit_started`，再执行第一次可能提交的动作。持久化失败不点击；点击已发出后即使超时，也不换候选按钮重发。微博多步骤在下一步前记录边界，两步各点一次；下一步异常或最终文案读回失败，同样保留提交后的不确定状态。

抖音预览在编辑器打开前精确阻断 `https://creator.douyin.com/web/api/media/aweme/create_v2/`（包括其查询参数），保证早期封面准备期间创建请求也不能发出；封面完成后再安装 DOM 发布按钮与快捷键保护。正式模式不安装该阻断规则，而是在提交边界前安装被动响应监听。

明确接口回执只接受官方域名的精确 `POST /web/api/media/aweme/create_v2/`，其请求 `item.common.media_type` 必须为数值 `43`；HTTP 2xx、响应根字段 `status_code` 为数值 `0`、根字段 `item_id` 为有效正整数字符串时，记录 `submitted` 与内容 ID。其他代码或格式交由页面证据核对。该规则参考[官方提交组件](https://lf-fe-creator.douyinstatic.com/obj/douyn-creator-scm-cdn/douyin-creator-content-new/micro/static/js/async/1060.abf5c0f7.js)及[官方文章组件](https://lf-fe-creator.douyinstatic.com/obj/douyn-creator-scm-cdn/douyin-creator-content-new/micro/static/js/async/4301.fe9b29ea.js)，不主动调用平台发布接口，也不从 ID 构造公开地址。接收回执不能证明文章已审核通过或公开发表。

`unknown` 或已记录 `submit_started` 的任务，需要人工核查平台记录后通过 `resolve` 记录依据，确认未提交才可重试。预览不点击正式发布，平台可能自动保存草稿。验收账号的账号名、Cookie、私人目录、内容截图中的账号信息不得加入公开文档。

后续每个平台按同一顺序验收：登录 / 权限 → 标题与正文格式或显式图片笔记转换 → 三张图片及顺序（长文章还需核对相邻段落）→ 封面 → 原生话题与专属选项 → 预览证据 → 一次正式提交回执 → 公开内容标题与链接。分别更新上述表格；平台或运行环境不具备时保留「未验证」，不能以其他平台通过代替。
