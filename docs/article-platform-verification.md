# 原生文章平台验证记录

本记录区分平台登记、代码实现、真实预览、平台接收回执和正式发表。当前 28 个平台能力通过统一任务服务执行，包含原生文章和图片笔记；车家号、易车号、懂车号依据当前官方文章页面完成专属适配。京东长文章 `jingdong`（类型 18、`style=0`）与京东图文 `jd`（类型 26、`style=25`）分别适配，不混用正文和封面规则。抖音完整真实预览已通过；其正式发布已取得官方文章创建成功回执及内容 ID，公开文章已现场核实。其余 27 个能力未完成真实账号验收，使用者仍需在自己的账号上验证实际流程。

## 已记录的真实验证状态

抖音真实验收日期：2026-10-01；汽车平台官方依据更新于 2026-10-03。仅有抖音验收账号；公开原稿为官网文章编号 927，包含三张正文图片。原稿和素材先导入 PostSail，官网发布流程仍独立。本次抖音验收限定为一篇文章的标题、完整正文、三张正文图及顺序、平台 CDN 地址和高清封面；原生话题、声明、其他账号和其他操作系统未验收。公开地址来自平台管理页分享字段和浏览器真实重定向，并非根据内容 ID 推测。

| 平台 | 原生内容 | 编辑器与素材准备 | `previewed` | `submitted` | `published` |
| --- | --- | --- | --- | --- | --- |
| 抖音 | 原生文章 | 标题、完整正文、三图顺序与平台 CDN 地址、高清封面均读回通过 | 已通过 | 已取得官方成功回执及内容 ID | 已现场核实公开文章 |
| B站 | 专栏 / 长图文 | 缺少真实验收账号 | 未验证 | 未执行 | 未执行 |
| 百家号 | 文章 | 缺少真实验收账号 | 未验证 | 未执行 | 未执行 |
| 今日头条 | 文章 | 缺少真实验收账号 | 未验证 | 未执行 | 未执行 |
| 微博 | 头条文章 | 缺少真实验收账号 | 未验证 | 未执行 | 未执行 |
| 知乎 | 文章 | 缺少真实验收账号 | 未验证 | 未执行 | 未执行 |
| 企鹅号 | 文章 | 缺少真实验收账号 | 未验证 | 未执行 | 未执行 |
| 搜狐号 | 文章 | 缺少真实验收账号 | 未验证 | 未执行 | 未执行 |
| 一点号 | 文章 | 公开契约与受控页面验证；缺少真实验收账号 | 未验证 | 未执行 | 未执行 |
| 大鱼号 | 文章 | 公开契约与受控页面验证；缺少真实验收账号 | 未验证 | 未执行 | 未执行 |
| 网易号 | 文章 | 公开契约与受控页面验证；缺少真实验收账号 | 未验证 | 未执行 | 未执行 |
| AcFun | 文章投稿 | 原生文章链接与控件需运行时核实；缺少真实验收账号 | 未验证 | 未执行 | 未执行 |
| 快传号 | 文章 | 公开契约与受控页面验证；缺少真实验收账号 | 未验证 | 未执行 | 未执行 |
| 雪球号 | 长文章 | 公开契约与受控页面验证；缺少真实验收账号 | 未验证 | 未执行 | 未执行 |
| 京东长文章 `jingdong` | 原生文章（`style=0`） | 官方源码与真实编辑器组件的离线 Chromium 回读；缺少真实验收账号 | 未验证 | 未执行 | 未执行 |
| 豆瓣 | 日记文章 | 公开契约与受控页面验证；缺少真实验收账号 | 未验证 | 未执行 | 未执行 |
| CSDN | 博客文章 | 公开契约与受控页面验证；缺少真实验收账号 | 未验证 | 未执行 | 未执行 |
| 简书 | 文章 | 公开契约与受控页面验证；缺少真实验收账号 | 未验证 | 未执行 | 未执行 |
| 车家号 | 原生长文 | 官方正文与双封面组件离线验证、受控浏览器回归；缺少真实验收账号 | 未验证 | 未执行 | 未执行 |
| 易车号 | 文章 | 官方双封面编辑组件离线验证、受控浏览器回归；缺少真实验收账号 | 未验证 | 未执行 | 未执行 |
| 懂车号 | 文章 | 官方正文、图片与封面组件离线验证、受控浏览器回归；缺少真实验收账号 | 未验证 | 未执行 | 未执行 |
| 快手 | 图片笔记 | 已接入准备与读回流程，缺少真实验收账号 | 未验证 | 未执行 | 未执行 |
| 视频号 | 图片笔记 | 已接入准备与读回流程，缺少真实验收账号 | 未验证 | 未执行 | 未执行 |
| 小红书 | 图片笔记 | 已接入准备与读回流程，缺少真实验收账号 | 未验证 | 未执行 | 未执行 |
| 微信公众号 | 公众号文章 | 已接入准备与读回流程，缺少真实验收账号 | 未验证 | 未执行 | 未执行 |
| 京东图文 `jd` | 图片笔记 | 已接入准备与读回流程，缺少真实验收账号 | 未验证 | 未执行 | 未执行 |
| 小红书商家号 | 商家图片笔记 | 已接入独立店铺 / 商品核对与准备流程，缺少真实验收账号 | 未验证 | 未执行 | 未执行 |
| 淘宝光合 | 图片笔记 | 已接入素材库上传、声明选择与准备读回流程，缺少真实验收账号 | 未验证 | 未执行 | 未执行 |

此前接入的十个平台及新增三个汽车平台的 `live_verified` 和 `verification.preview/submitted/published` 均为 `false`。受控页面只证明实现面对固定页面结构时符合预期，不能证明当前平台页面、真实账号权限或正式发布可用。京东长文章和三个汽车平台使用公开官方组件补充了离线回读验证，仍未执行真实账号登录、图片上传或正式发布。代码启用不计作真实平台验收。

抖音真实页面已核实标题上限30字、摘要上限30字、正文上限20000字、正文图片上限30张、原生话题最多5个，以及封面宽高均至少500px。初始封面为322×520px，平台明确拒绝低分辨率；不能把触发文件选择器算作封面设置成功。

正文预览失败已定位到超链接：平台将链接转换为 `span[data-dy-warning]`，追加「该文本类型暂不支持，请替换素材」，其余正文读回一致。新增 `options.links_as_text`，默认关闭；用户显式开启后，将链接转换为「原文字（完整网址）」，保留原稿与完整网址，并保存任务转换稿。本次显式开启该配置后，完整正文和三张图片的相邻段落、顺序及平台地址已通过读回，高清封面也已保存并读回，最终预览任务的 `submit_started=0`。此次没有真实原生话题与声明的验收证据，其他选项不能由正文、封面通过推定成功。

封面准备改为先于标题与正文，等待裁剪背景和文字两层生成图解码后单次点击「完成」，再核对新的平台 CDN 封面。独立封面保存与完整文章预览均已取得成功证据；此前仅看到分辨率或原始图片，不能证明平台已完成封面图层合成与保存。

随后进行一次正式提交，接口回执阶段任务记录 `status=submitted`、`submit_started=1`、`attempts=1`。官方文章创建响应返回有效内容 ID，页面同时出现真实「发布成功」提示。随后从管理页实际返回的分享地址打开公开文章，使用未加载验收账号会话的浏览器核对，真实重定向到[抖音公开文章](https://www.douyin.com/article/7691535675165871406)，页面显示正确短标题、日期与完整正文。本轮 `previewed`、`submitted`、`published` 三个层次均已取得现场依据。

## 各状态的证据门槛

| 层次 | 必须取得的依据 | 不能作为依据的情况 |
| --- | --- | --- |
| 代码接入 | 平台注册、专属入口、选项处理和回归用例存在 | 仅新增下拉选项或平台名称 |
| 账号会话有效 | 会话结构与目标域名校验，平台返回正向登录依据 | Cookie 键存在、文件存在、URL 没有报错 |
| 内容权限可用 | 能打开该账号所选内容形态的编辑器并定位可编辑字段 | 已登录视频后台，或把图片笔记误作长文章编辑器 |
| `previewed` | 标题、正文、所选形态的排版、图片数量 / 顺序 / 平台地址、封面与原生选项完整读回，并保存准备证据；图片笔记还须满足显式转换规则 | 粘贴操作成功、仅截图、已打开编辑器、平台自动保存草稿 |
| `submitted` | 取得严格匹配本次文章请求的成功响应，或编辑器外出现明确的发布 / 接收 / 审核回执 | 点击过按钮、管理页跳转、正文出现「发布成功」文字 |
| `published` | 已打开可核实的公开文章地址，正文页面含预期标题，并记录内容 ID / URL | 单纯发布成功提示、仍处于审核、列表链接未经核对 |

API 返回 `verification.preview/submitted/published` 分别表示真实验收层次，不能用一项替代另外两项。能力字段以运行版本的实际返回为准；每个发布任务另外保存自己的实际状态与证据。更新全局能力字段应对应可复查的逐平台验收记录，不能用抖音单次正文与封面预览宣称所有话题、声明或其他账号均已验收。

## 原生入口与实现依据

| 平台 | 入口 / 依据 | 目前限制 |
| --- | --- | --- |
| 抖音 | [原生文章创作入口](https://creator.douyin.com/creator-micro/content/post/article)；真实账号 DOM 与官方公开微前端脚本 | 正文超链接需显式转换；封面和原生话题均需读回 |
| B站 | [当前专栏编辑器](https://member.bilibili.com/york/read-editor)；官方公开编辑器脚本 | 当前适配标题最多30字；旧专栏入口已下线；当前编辑器没有可配置分类 |
| 微博 | [头条文章编辑器](https://card.weibo.com/article/v3/editor)；[微博长文官方 PC 教程](https://www.weibo.com/ttarticle/p/show?id=2309404803154729631808)；[公开维护者浏览器脚本](https://github.com/jimliu/baoyu-skills/blob/main/skills/baoyu-post-to-weibo/scripts/weibo-article.ts) | 「下一步」与最终短微博「发布」分开处理；原生话题没有确切控件证据时要求人工处理 |
| 企鹅号 | [文章创作入口](https://om.qq.com/main/creation/article)；[近期维护者源码](https://github.com/liuxucai/qq-publish-skill/blob/master/scripts/publish_isob.js)；[维护者流程记录](https://github.com/liuxucai/qq-publish-skill/blob/master/references/workflow.md)；[文章适配器参考](https://github.com/yjmm10/MediaSync/blob/master/packages/core/src/adapters/platforms/qiehao.ts) | 新编辑器标题 / ProseMirror 优先，旧 UEditor 兼容；封面、分类、摘要、自主声明和标签须实际控件命中与读回；缺账号尚未验收 |
| 百家号、知乎、今日头条、搜狐号 | 现有独立文章 uploader，经统一准备与结果读取流程接入 | 缺账号尚未验收；声明、封面与话题失败会阻止提交 |
| 一点号 | [文章编辑器](https://mp.yidianzixun.com/#/Writing/articleEditor)；MediaSync 的 `yidian.ts`、MultiPost 的 `yidianzixun.ts`；蚁小二文章契约 | 标题 5–64 字；封面必填；不支持独立标签；公开脚本中的占位封面选择器未作为成功依据 |
| 大鱼号 | [文章编辑器](https://mp.dayu.com/dashboard/article/write)；MediaSync 的 `dayu.ts`、MultiPost 的 `dayuhao.ts` | 标题上限50字、正文 HTML 上限50000字符；进入实际 UEditor iframe 读写正文 |
| 网易号 | [文章编辑器](https://mp.163.com/subscribe_v4/index.html#/article-publish)；MediaSync、MultiPost 的 `netease.ts` | 新旧标题提示不同，须读取实际控件限制；Draft.js 正文；封面必填 |
| AcFun | [会员中心](https://www.acfun.cn/member/)；蚁小二 `article/acfun.md` | 从当前页面读取唯一的「文章投稿」链接，严格核实文章路径；不猜视频入口；分类和封面必填，最多一个话题 |
| 快传号 | [原生文章编辑器](https://kuaichuan.360kuai.com/#/console/publish/article)；MultiPost 的 `kuaichuanhao.ts`；蚁小二文章契约 | 360 快传号；封面必填；标题限制以实际控件为准 |
| 雪球号 | [长文章编辑器](https://mp.xueqiu.com/writeV2)；MultiPost、Wechatsync 的 `xueqiu.ts` | 标题 9–100 字；ProseMirror 正文；可见范围与声明须原生控件读回 |
| 京东长文章 `jingdong` | [原生文章编辑器](https://dr.jd.com/n/publish-article.html)；官方文章、分类与 Braft 组件；蚁小二正式网页文章契约 | `style=0`；每任务 1 张独立封面；可选精确三级分类；核验原生表单序列化内容，真实账号尚未验收 |
| 豆瓣 | [日记编辑器](https://www.douban.com/note/create)；MultiPost、Wechatsync 的 `douban.ts` | 日记文章；无独立封面；日记预览与最终发表动作分开处理 |
| CSDN | [博客富文本编辑器](https://mp.csdn.net/mp_blog/creation/editor)；SyncCaster 的 `csdn.ts`；蚁小二文章契约 | 摘要、创作类型、标签和封面必填；打开发布设置期间阻止未经核实的写请求，核验后才进入正式提交边界 |
| 简书 | [写作页面](https://www.jianshu.com/writer)；SyncCaster、MediaSync 的 `jianshu.ts` | 先新建独立文章并确认新稿 ID，再切换可核实的富文本正文；无独立封面和标签，不覆盖旧稿 |
| 车家号 | [当前原生长文入口](https://creator.autohome.com.cn/web/publish/long)；官方 Lexical、封面与提交组件 | 独立双封面；链接须显式转换；上传协议必须明确同意；真实账号尚未验收 |
| 易车号 | [原生文章入口](https://mp.yiche.com/article/index-new)；官方 Nuxt 文章、Quill 与双封面组件 | 以原生素材键核验 Base64 预览；六种声明与转载来源；真实账号尚未验收 |
| 懂车号 | [原生文章入口](https://mp.dcdapp.com/profile_v2/publish/article)；官方 Syl 正文、双封面与提交组件 | 正文标题只支持 H1；独立双封面和素材 URI 读回；真实账号尚未验收 |
| 小红书 | [图片笔记入口](https://creator.xiaohongshu.com/publish/publish?from=homepage&target=image)；[上游 XiaoHongShuNote](https://github.com/dreammis/social-auto-upload/blob/0012d2c355f88f683cc38dde2a2db209e14091bc/uploader/xiaohongshu_uploader/main.py) 的图片输入与标题 / 描述控件 | 图片列表加描述；富文本转换须显式启用，缺账号尚未验收 |
| 快手 | [创作者发布入口](https://cp.kuaishou.com/article/publish/video)切换「图文」；[上游 KSNote](https://github.com/dreammis/social-auto-upload/blob/0012d2c355f88f683cc38dde2a2db209e14091bc/uploader/ks_uploader/main.py) 的图文标签、上传图片与描述控件 | 标题并入描述首行；缺账号尚未验收，不复用上游循环点击发布逻辑 |
| 视频号 | [视频号助手发布入口](https://channels.weixin.qq.com/platform/post/create)；[公开维护者源码](https://github.com/3441293738/creatorhub/blob/c588dd58e67dc7feed01d175edfd295e59e8f647/app/platforms/channels/publish.py)描述跨 iframe 的「图文」→「发表图文」路径及描述 / 短标题控件 | 公开源码标注实验性；尚缺真实账号页面校准。不能以进入视频发布页证明图文权限 |
| 微信公众号 | [公众号后台](https://mp.weixin.qq.com/)；[公开编辑器脚本](https://github.com/jimliu/baoyu-skills/blob/main/skills/baoyu-post-to-wechat/scripts/wechat-article.ts)的 `.rich_media_content .ProseMirror`、标题 / 作者 / 摘要控件；[入口与草稿适配参考](https://github.com/yjmm10/MediaSync/blob/master/packages/core/src/adapters/platforms/weixin.ts)；[发表确认控件参考](https://github.com/Marshall-Jimmy/wechat-auto-publisher/blob/main/core/wechat_publisher.py) | `#js_submit` 与 `operate_appmsg sub=create` 只保存草稿，不算正式发布；发表扫码需人工确认，缺账号尚未验收 |
| 京东图文 `jd` | [图文入口](https://dr.jd.com/n/publish-graphic.html)；官方公开脚本[图文创建](https://storage.360buyimg.com/ifloors/talent-platform-new/1790145277602/assets/index-CfC4YrbB.js)、[标题 / 封面 / 商品抽屉](https://storage.360buyimg.com/ifloors/talent-platform-new/1790145277602/assets/index-DkYQO5-I.js)、[关联挂件](https://storage.360buyimg.com/ifloors/talent-platform-new/1790145277602/assets/index-D0qBDxJW.js)、[上传与账号信息](https://storage.360buyimg.com/ifloors/talent-platform-new/1790145277602/assets/main-Buzi2ykr.js) | 与文章入口分开；每图≤5MB，首图生成3:4封面需核验；商品最多10个，账号或频道另有必填要求时停止；缺账号尚未验收 |
| 小红书商家号 | [商家登录](https://customer.xiaohongshu.com/login?service=https://ark.xiaohongshu.com/ark/home)、[商品笔记入口](https://ark.xiaohongshu.com/app-note/publish)；[固定版本公开浏览器流程](https://github.com/gaoming714/ByteScript/blob/c9f8d46a4e453f83d9c1e5a9b8b135fb53b4244b/xiaohongshu0x01.py)中的店铺、商品和手动创作图文路径 | 独立商家会话；必填准确商品 ID 和完整店铺名；9张图片为保守限制。缺少店铺或商品关联读回即停止；缺账号尚未验收 |
| 淘宝光合 | [光合后台](https://creator.guanghe.taobao.com/)；固定版本[图文与素材库流程](https://github.com/Jiarenzaigusu/multi-platform-auto-upload-main-DAM-newest/blob/753566cefe5d0e3319fe52d34f3bb5485d740c08/uploader/tmall_article_uploader/main.py)、[图片 / 封面限制参考](https://github.com/yixiaoer888/yixiaoer-skill/blob/a2722c6095f57abf2e345dca637bdded44fa34df/skills/yixiaoer/references/platforms/imageText/taobaoguanghe.md)、[声明选项参考](https://github.com/DevilJie/social-auto-upload-web-ui/blob/8e33adf0e461ecbc992be244f241c6590adc608f/backend/impl/taobao_guanghe/platform.py) | [完整图文入口](https://creator.guanghe.taobao.com/page/pubNew/pic?pub_url=https%3A%2F%2Fhuodong.taobao.com%2Fwow%2Fz%2Fguang%2Fgg_publish%2Fgg-picture%3Fugc_scene%3Dpc_newcreator_pic%26pageType%3Darticle%26site%3Dguangguang&pub_scene=gg)包含 iframe 路径 `/gg_publish/gg-picture`；素材库只选择本次上传的唯一文件名；必选声明；缺账号尚未验收 |

引用公开源码用于确认入口与控件，并不代表当前用户已经登录、该账号具有文章权限或本项目已经发布成功。公开脚本中以 DOM 修改、盲选第一个按钮或管理页跳转认定成功的做法，不作为本项目结果判定依据。

## 新增平台的研究依据与验证边界

按用户要求的「文章发布」类别查阅蚁小二公开契约，再交叉核对开源编辑器实现；PostSail 直接使用目标平台浏览器页面，不调用蚁小二的账号或发布服务。参考版本固定如下，便于复查当时的依据：

| 公开资料 | 固定版本 | 本轮使用范围 |
| --- | --- | --- |
| [蚁小二文章平台契约](https://github.com/yixiaoer888/yixiaoer-skill/tree/a2722c6095f57abf2e345dca637bdded44fa34df/skills/yixiaoer/references/platforms/article) | `a2722c6` | 一点、大鱼、网易、AcFun、快传、雪球、豆瓣、CSDN、简书，以及车家号、易车号的文章类型、必填项及已公开限制 |
| [MediaSync 平台适配器](https://github.com/yjmm10/MediaSync/tree/77ec95860fd1b0898459a6f401220e34cf80f31e/packages/core/src/adapters/platforms) | `77ec958` | 一点、大鱼、网易的编辑入口，以及部分平台的只读身份信息和写作页 |
| [MultiPost 文章脚本](https://github.com/leaper-one/MultiPost-Extension/tree/6269ab4ada1cf661a3624b2b9f496bb032a391d5/src/sync/article) | `6269ab4` | 一点、大鱼、网易、快传、雪球、豆瓣的编辑器与控件候选；车家号和懂车号的入口候选，未据此启用汽车平台 |
| [Wechatsync 平台适配器](https://github.com/wechatsync/Wechatsync/tree/a98e42865387285afcc027c61836488748f3b30f/packages/core/src/adapters/platforms) | `a98e428` | 豆瓣、雪球的文章入口与页面身份信息 |
| [SyncCaster 平台适配器](https://github.com/RyanYipeng/SyncCaster/tree/7ba05f4870b9ae25d55ca8acdf1bfeba08045802/packages/adapters/src) | `7ba05f4` | CSDN 富文本入口、简书 kalamu 编辑器和新建文章流程 |

标题上限未有可靠公开依据的网易、快传、豆瓣、CSDN、简书，能力表中的 `title_max:300` 仅沿用本地原稿上限，`title_limit_confirmed:false`。实际执行仍检查原生标题控件的限制与完整读回，不能将300字写成平台支持承诺。豆瓣、简书明确不使用独立封面；一点、大鱼、网易、雪球、京东长文章、简书没有独立话题字段，不继承原稿默认 `tags`，也不会把普通正文文字冒充原生标签。

### 三个汽车平台的官方依据

车家号 `chejiahao`（账号类型 22）、易车号 `yiche`（23）、懂车号 `dongchedi`（24）的官方页面和公开脚本已于 2026-10-03 只读取得。三个原生适配器均已开放执行，支持独立双封面、正文与选项读回、预览保护和单次正式提交。公开源码和离线组件验证不构成真实账号的登录、图片上传、预览或发布证据，三者的 `live_verified` 和三项 `verification` 仍为 `false`。

此前参考的蚁小二 [车家号](https://github.com/yixiaoer888/yixiaoer-skill/blob/a2722c6095f57abf2e345dca637bdded44fa34df/skills/yixiaoer/references/platforms/article/chejiahao.md)、[易车号](https://github.com/yixiaoer888/yixiaoer-skill/blob/a2722c6095f57abf2e345dca637bdded44fa34df/skills/yixiaoer/references/platforms/article/yichehao.md)文档及[正式网页业务脚本](https://www.yixiaoer.cn/web/assets/index-vGO4Yq33.js)用于确认文章类别与字段候选。原生页面与该契约不同的标题、封面和声明约束，以当前官方依据为准。PostSail 直接操作平台页面，不调用蚁小二发布服务。

| 官方资源 | SHA-256 | 确认内容 |
| --- | --- | --- |
| [车家号 main.66716c76.js](https://creator.autohome.com.cn/web/static/js/main.66716c76.js) | `21a4b0cf10da3f4a347bff1bd38956bd14e2ce75b3e2cf49d09f2224dbf711f2` | `/web/publish/long`、Lexical 正文、横竖封面、原创与首发、上传协议和长文提交 |
| [车家号封面美化 Index-Uq50sxX_.js](https://posterdesign.autohome.com.cn/assets/Index-Uq50sxX_.js) | `7ff3cd64d360a8b4eaafefb98222c0c72da0d9d3bafcd87ce982a9288d6d994c` | 美化 iframe 的就绪及取消交互，取消美化保留已选原图 |
| [易车号 6657c87.js](https://mp.yiche.com/_nuxt/6657c87.js) | `72a947affa644c4cfd3f71cce72a844a6ebcc0b60b609f1a1b775a574fb34b12` | `/article/index-new`、Quill 正文、双封面裁剪组件、六种声明和提交字段 |
| [易车号 49f3426.js](https://mp.yiche.com/_nuxt/49f3426.js) | `7fdf1821f47eacdcce3c7b0e9f81a618f7db1452dc6cd16201266445b7a89774` | 原生上传与 `savenews` 地址、请求封装 |
| [懂车号 PublishArticle.9031c083.js](https://lf3-motor.dcarstatic.com/obj/motor-fe-static/motor/mp/v2/static/js/async/PublishArticle.9031c083.js) | `34ebd912c2ad6bd68e66e62d8221ec595ac138666bfe88df87f75280e84bbe5d` | `/profile_v2/publish/article`、正文图片节点、横竖封面、校验与提交载荷 |
| [懂车号 7621.6951dfe3.js](https://lf3-motor.dcarstatic.com/obj/motor-fe-static/motor/mp/v2/static/js/async/7621.6951dfe3.js) | `0fcd7f338f2ec6ecf6f91e4eb5052379b88382c248a25f8c00c37be8da54d464` | 双封面编辑组件、上传状态、素材 URI 与持久图片地址 |

| 平台 | 当前配置与原生依据 | 仍需真实账号验收 |
| --- | --- | --- |
| 车家号 | 原生加权标题 6–30 字、正文 10–100000 字；UTF-16 码元数值大于 256 计 1 字，其余计半字；横封面 4:3、至少 560×420px，竖封面 3:4、宽度至少 560px、高度至少 420px，建议 600×800px，各 ≤10MiB | 当前账号的长文权限、完整正文与双封面上传、原生选项、提交及公开文章 |
| 易车号 | 原生标题 5–28 字；正文 HTML 上限配置为 8000 字符；横封面 3:2，竖封面 3:4 或 4:3；各 ≤10MiB、宽度 ≤5000px | 当前账号权限、Quill 正文及上传素材键、完整双封面流程、提交及公开文章 |
| 懂车号 | 标题 2–30 字且至少 2 个汉字；原生正文去空白后 ≤50000 个 UTF-16 码元、原生 HTML ≤60000 个码元；横封面 4:3、至少 532×399px；竖封面 3:4、至少 534×712px；各 ≤20MiB | 当前账号权限、正文与封面素材 URI、最终提交及公开文章 |

车家号旧入口 `/article/post.html` 已返回 404，当前长文使用 `creator.autohome.com.cn/web/publish/long`。当前官方 `Qi` 计数函数（模块 85311）采用上述加权口径，因此纯 ASCII 标题允许 12–60 个字符；早期契约中的「至少六个汉字」不再沿用。官方 Lexical 编辑器会移除超链接；含链接原稿须显式启用 `links_as_text` 才能转换为链接文字与完整网址，转换稿另存且保留原稿。用户须明确设置 `agree_upload_terms:true`，同意《汽车之家内容上传服务条款》《汽车之家联合共创须知》。目标账号要求内容属性时，须显式选择「非商业内容」或「商业内容」，不能由系统猜测。

原生标题控件另行拒绝 Emoji 等特殊符号（包括 U+2600–U+27FF 和 UTF-16 代理对）；加权长度符合要求也不能跳过字符校验。

车家号离线浏览器验证加载当前官方 Lexical、双封面选择和声明组件，核对 H2、加粗、正文图原生绑定、横竖封面表单字段及协议读回，浏览器无未处理错误。账号上下文与上传响应为本地模拟；封面美化 iframe 仅复现已核实的 `postMessage` 就绪和关闭交互。该结果验证组件和适配器的衔接，没有执行真实账号登录、素材上传或发布。

易车号原生声明为「内容无需标注」「含AI生成内容」「含虚构演绎内容」「内容含营销信息」「个人观点，仅供参考」「内容为转载」；最后一项必须提供 `source_url`。早期蚁小二契约中的「不声明」「内容来源网络」「AI生成」「引用站内」不自动映射，已有原稿须重新选择。`allow_forward` 表示同意转发，`allow_abstract` 表示同意生成摘要，两项均默认关闭。三个汽车平台均不继承普通 `tags`，未开放原生话题、定时或平台草稿选项。

易车官方 VueCropper 与 VueImageEditor 组件的离线浏览器验证确认，3:4 和 4:3 封面可保留完整画面，四角测试标记均保留。原生组件配置 `maxImgSize:2000`，可能缩放及重新编码，不承诺原像素尺寸或字节不变。此验证没有真实账号、素材上传或发布。

三个平台的横封面使用 `cover_asset_id`，独立竖封面使用 `options.vertical_cover_asset_id`。后者是 `type:asset` 的已上传素材 ID，不接受服务器文件路径；原稿默认配置与任务快照保护素材引用，已引用素材不能删除。系统不从横封面自动生成竖封面。易车官方页面用 `imgBase64` 展示图片、用 `imgKey` 提交素材；懂车的封面预览也可能保留本地地址。此类预览只有与原生上传成功状态、素材键或 URI、待提交数据一致才可作为准备依据，单独显示图片不能证明上传成功。

懂车号官方正文组件会将 H2–H6 导入为 H1。本版本通过 `heading_levels:[1]` 在准备前明确拒绝 H2–H6；用户可在原稿编辑器主动选择 H1 或普通段落并保存新修订。系统不会自动改变标题层级，也不会将不支持的标题转成图片。表格与代码块的通用图片转换不代表其他格式也能自动回退。

懂车号原生组件可能把正文首图设为封面，适配器因此先上传用户指定的横竖封面，再填写正文，最终再次读回。未经请求的独家、活动、原创、定时或商业稿状态会阻止提交；作品同步授权仅通过原生关闭操作拒绝本次额外同步，不能自动开启其他平台同步或修改永久偏好。

懂车官方 Syl 正文及图片组件的离线浏览器验证覆盖真实序列化、可见正文与图片节点的绑定；官方封面组件（模块 70421）及 `PublishImage`（模块 1752）的独立验证确认本次原生对象与可见图片绑定，解码失败的预览会被拒绝。图片响应由隔离页面提供，未向懂车上传素材，不能视为平台接收回执或真实账号验收。

历史回归：2026-10-02 的 523 项本地测试及另行运行的 73 项共享专项通过，开启了受控浏览器测试；前端构建、汽车账号禁用提示、文章目标禁用提示和模拟启用下的封面组件通过检查。当时能力 API 为 21 个登记、18 个可执行、3 个禁用。该轮验证覆盖配置、素材引用和禁用边界，不包含本轮原生适配或真实账号发布。

合并前 main 分支在 2026-10-03 的完整回归开启 `OMNIPOST_BROWSER_TESTS=1`，运行 `python -m unittest discover -s tests`，589 项全部通过、无跳过，耗时 245.017 秒；另行运行的 83 项共享专项也全部通过。前端生产构建通过，运行中能力 API 已读回 21 个可执行平台。网页检查包含三个汽车账号入口、横竖封面真实文件上传控件、车家号协议选择、易车转载来源和 H1 编辑按钮，未出现未处理的浏览器错误。这些本地检查未向外部平台发文。

### 京东长文章 `jingdong` 的原生依据

原接入的京东长文章对应 `jingdong`、账号类型 18，使用京东创作服务平台的原生文章。官方旧版路由将 `/new_create/0` 迁移到 [`/n/publish-article.html`](https://dr.jd.com/n/publish-article.html)，明确区分文章 `style=0`、图文 `style=25` 和视频 `style=2`。当前文章页面根节点为 `.dr-publish-article-wrapper[data-spm-c="c00009560"]`，正文使用 `#module-richtextNew #richtext-editor-box` 下的 Braft / Draft.js 编辑器；旧稿身份或非空已有正文会阻止覆盖。

本次只读核对的官方公开资源如下：

| 官方资源 | SHA-256 | 确认内容 |
| --- | --- | --- |
| [文章组件 index-CdTwnNcS.js](https://storage.360buyimg.com/ifloors/talent-platform-new/1790145277602/assets/index-CdTwnNcS.js) | `4c3bcc30b8bb34657515a329bd0b79731375ffcb90c4015224f78772be6776be` | 原生文章页面、正文序列化、图片上传、封面、提交与草稿的独立路径 |
| [分类组件 index-CtzUM7Yv.js](https://storage.360buyimg.com/ifloors/talent-platform-new/1790145277602/assets/index-CtzUM7Yv.js) | `fd9fae2190264dab10d781992f0fecc79a608a26497a352ab0db9d1b2ac9ff89` | 三级标签类型、叶子选项及分类 ID 序列化 |
| [级联控件 index-B60HG0SX.js](https://storage.360buyimg.com/ifloors/talent-platform-new/1790145277602/assets/index-B60HG0SX.js) | `0980e42eb77a507c4d5843eef0193c53ca9e78d9c5a69c86c1b527b886785010` | 菜单列、精确选项标题、悬停展开和选中状态 |
| [蚁小二正式网页业务脚本](https://www.yixiaoer.cn/web/assets/index-vGO4Yq33.js) | `6fc2f82740e73659e4b6249477391c5074e47fbb899dde2fa21d4870de91a2b4` | `JingDong` 的文章表单，以及标题、封面与分级标签约束 |

蚁小二的 `bde[A.JingDong] = ode` 将京东加入文章能力表，`ufe[A.JingDong] = UB` 创建包含 `title`、`covers`、`tagType` 和 `pubType` 的文章表单。标题要求15–27字，封面比例10:7、至少600×420像素、单张不超过5MiB，并提示不能选正文首图，不能带水印、文字或logo。其表单允许1–3张封面；PostSail 本版本每任务使用1张独立封面，通过素材 ID 和文件哈希拒绝复用正文首图。蚁小二的标签和草稿字段只是交叉参考，PostSail 直接操作京东原生页面，不调用蚁小二账号或发布服务，也不开放平台草稿选项。

京东正文图片走原生上传控件，要求宽高均至少300px、单张不超过5MiB；不自动放大或裁剪不合格的原图。封面与正文上传后均须取得新的持久平台地址，本地 `blob:` 预览不能证明上传成功。可选 `options.category` 每任务选择1个完整的「一级/二级/三级」精确分类路径，逐层展开并确认叶子选中；普通 `tags` 不会冒充分级标签。实际标题、封面和其他必填字段由平台按账号或频道下发，当前页面出现更严格限制或未支持的必填字段时会停止。

官方 Braft 配置会剥离普通粘贴样式，因此正文通过编辑器公开状态 API 和正常变更回调导入，保留原生表单变更链。校验同时检查可见正文与 `getRteContents()` 产生的发布正文；原生序列化可能移除可见的尖括号字面量，仅核对 DOM 不足以证明内容完整。格式、完整文本、链接目标、图片地址及顺序都须与准备稿一致，未知原生卡片不能直接跳过。含超链接的文章还要求当前账号可见原生「超链接」工具；没有此权限控件时停止。表格和代码块使用通用 PNG 回退，生成图片同样必须满足正文图片尺寸下限，不足时不会自动放大。

离线 Chromium 加载了公开官方编辑器组件，验证公开 API、正常回调和原生正文序列化，包含富文本、图片及尖括号字面量等样例。该验证没有京东会话，没有向京东上传素材或提交文章；真实账号权限、服务端动态配置、图片持久化、验证码和发布回执仍需现场验收。官方成功文案为“发布成功，等待审核！”，只能对应 `submitted`；内容列表跳转也可能来自保存草稿，不能据此标记 `published`。

此前新增十个平台的验证使用临时数据库、虚构会话、模拟网络响应与本地受控浏览器页面，覆盖账号类型隔离、官方域名边界、正向身份确认、原稿快照与幂等、必要选项、正文与素材读回、预览保护及单次提交边界。没有使用这些平台的真实账号，也没有为它们执行真实正式发布；这十个平台仍须逐个补齐本记录中的真实预览、接收回执和公开发表证据。三个汽车平台也未进行真实账号登录、上传或发布，不以官方组件离线验证代替真实验收。

### 合入的图片笔记与微信公众号能力

合并版本新增小红书 `xiaohongshu`（类型 1）、快手 `kuaishou`（4）、视频号 `tencent`（2）、微信公众号 `wechat`（25）、京东图文 `jd`（26）、小红书商家号 `xiaohongshu_merchant`（27）及淘宝光合 `taobao`（28）。懂车号使用前述当前官方长文章与双封面实现，类型为 24。旧分支的数字类型冲突按[账号平台迁移](./account-platform-migration.md)处理；账号绑定确认不代表已登录或具有发布权限。上述七项能力均没有真实账号预览、上传或发布证据，`verification.preview/submitted/published` 保持 `false`。

六个图片笔记能力使用「文本描述 + 有序图片」。普通段落形成描述，链接保留文字与完整网址；含标题层级、加粗、列表、引用、表格或代码时，须显式设置 `options.flatten_content:true`。转换保留文字，去除富文本排版及图片与段落的交错布局，不把表格或代码改为图片。原稿不变。图片保持原始顺序，独立封面不在图片列表中时才加到首位；京东图文、淘宝光合要求已在列表中的指定封面必须为首图，否则停止。

限制采用当前配置与公开依据：小红书标题 20 字、描述 1000 字、18 张图；快手标题 90 字、含标题首行的描述 500 字、30 张图；视频号短标题 16 字、描述 1000 字、9 张图；京东图文标题 5–20 字、描述 1000 字、20 张图；小红书商家号标题 20 字、描述 1000 字、9 张图；淘宝光合标题 30 字、描述 1000 字、1–9 张图。均须至少一张图片，图片数包含前置封面。超限停止，不自动截断或丢图，当前页面更严格时也停止。这些配置未在真实账号上逐项验收。

小红书、快手、视频号、京东图文及小红书商家号仅把话题作为 `#文字` 追加到描述并计入字数，不保证原生话题关联，当前不提供创作声明选项。淘宝光合不支持非空话题，须明确选择六个原生声明之一。上传后须核对完整文本、有序图片和平台地址；选中本地文件或出现本地预览不足以证明上传完成。

微信公众号使用 `mp.weixin.qq.com` 的独立登录与原生编辑器，标题上限 64 字、作者 8 字、摘要 120 字，封面必填。`#js_submit` 与 `operate_appmsg sub=create` 仅保存草稿；扫码确认、审核中或管理页跳转也不能证明公开发表。真实权限、封面裁剪、正文图片上传和最终发布确认仍需现场验收。

京东图文的 20 字标题为保守上限；公开官方通用组件包含 5–27 字校验且可被页面覆盖，实际页面的最短标题与更严格上限仍须核对。每图最多 5MB，首图生成 3:4 封面后读回。可选 `product_links` 接受最多 10 个 SKU 或 `https://item.jd.com/商品编号.html` 链接，逐项核对，不默认关联商品；账号或频道要求商品而未配置时停止。官方 `articleSaveImageTextDraft` 与 `articlePublishImageText` 分别用于草稿和正式提交，草稿响应不能当作发布回执。此处的图片笔记规则不适用于类型 18 的京东长文章。

小红书商家号必须提供准确 `product_id`（最多 64 字）和后台完整 `shop_name`（最多 100 字），通过商家入口独立登录并核对当前店铺及关联商品。普通创作者会话不代表商家权限。店铺不匹配、商品或关联结果不明确时停止，不自动选取第一个商品。

淘宝光合的每张图片至少 720×720px、最多 20MB，首图为封面；通过图文 iframe 打开素材库，以唯一临时文件名选择本次上传的图片。图集 URL 须与本次素材卡片 URL 一致，平台改变缩略图地址形式而无法核对时停止。声明须明确选择「内容无需标注」「含AI生成内容」「含虚构演绎内容」「内容为转载」「个人观点，仅供参考」「内容含营销信息」之一，并读回选中状态。话题、商品、音乐、品牌与定时发布当前不支持。依据为上表公开维护者代码与契约，隔离测试不能证明当前真实账号页面已通过。

首次验收先登录目标后台确认权限，再运行 `sau article publish ... --preview` 检查准备证据和 `submit_started=0`。图片笔记检查转换后的完整描述、图片数量与顺序；商家号另行核对店铺与商品；长文章核对相邻段落及正文图片顺序。预览通过后，正式接收和公开发表仍分别需要真实证据。

## 合并版本回归范围

本次合并保留 main 的原生文章、官方组件离线证据，以及 work 的图片笔记和公众号转换、专属控件及提交边界用例。2026-10-03 开启 `OMNIPOST_BROWSER_TESTS=1` 运行 `python -m unittest discover -s tests -v`，752 项全部通过、无跳过，耗时 345.323 秒。随后对视频号等待导航期间异步恢复旧稿的情况补充点击前检查；修复后的完整图文专项 88 项全部通过、无跳过，耗时 68.486 秒，包含新增的延迟恢复回归。两组用例有重叠，不合计为独立用例数；752 项全量未在最后两文件的小修后重新运行。

前端生产构建通过。隔离浏览器配合真实 Flask API 和临时数据库验证 28 个能力、知乎／京东图文／小红书三个目标在筛选后仍完整提交预览任务，以及旧京东图文账号从类型 13 确认为 26 后生成数据库备份并保留 ID、会话文件与历史任务。另一组网页检查验证筛选后仍保留 11 个已选目标、三次竖封面上传及平台覆盖字段；两组检查均无未处理的页面异常。以上均为本地隔离验证，不向真实账号发布，不能代替各平台的真实验收。

视频号预览在进入图文表单前临时阻断网络写请求，进入表单后先安装完整的发表按钮和快捷键保护，再撤去临时请求阻断。导航若依赖写请求会停止并提示人工处理；不会全局放开其他平台的“发表图文”按钮。受控浏览器已验证导航、意外写请求阻断及异步旧稿恢复，真实账号流程仍待验收。

## 提交安全与后续验收

正式操作先持久化 `submit_started`，再执行第一次可能提交的动作。持久化失败不点击；点击已发出后即使超时，也不换候选按钮重发。微博多步骤在下一步前记录边界，两步各点一次；下一步异常或最终文案读回失败，同样保留提交后的不确定状态。

三个汽车适配器均在准备期间拦截正式文章请求，预览不会解除阻断。正式模式只在提交边界持久化后放行一条与本次标题、完整正文、图片、双封面及选项匹配的请求，回执必须属于同一条请求；重复请求和草稿不会被当作成功发布。车家号同接口的自动草稿请求也被拦截，避免准备过程取得草稿 ID 或更新已有稿件。

| 平台 | 正式文章请求 | `submitted` 的接口依据 |
| --- | --- | --- |
| 车家号 | `POST /openapi/content-api/gc/article/publish?publishType=1` | HTTP 2xx、整数 `returncode:0`，且 `result.id` 为有效正数 ID |
| 易车号 | `POST /web_mp/api/v1/pub/savenews`，`action:2`、`publishType:2`、`newsId:0` | HTTP 2xx、`status` 为 1、`data.result` 明确成功且非每日限制提示；有合法 `newsId` 才记录 ID |
| 懂车号 | `POST /motor/content_publish/publish_mp_article/v1`，`save:1`、`source:20` | HTTP 2xx、官方成功响应封装，且 `data.data.pgc_id` 为有效正数 ID |

上述回执只证明平台接收，不证明已经公开发表；不根据内容 ID 拼接公开文章地址。

抖音预览在编辑器打开前精确阻断 `https://creator.douyin.com/web/api/media/aweme/create_v2/`（包括其查询参数），保证早期封面准备期间创建请求也不能发出；封面完成后再安装 DOM 发布按钮与快捷键保护。正式模式不安装该阻断规则，而是在提交边界前安装被动响应监听。

明确接口回执只接受官方域名的精确 `POST /web/api/media/aweme/create_v2/`，其请求 `item.common.media_type` 必须为数值 `43`；HTTP 2xx、响应根字段 `status_code` 为数值 `0`、根字段 `item_id` 为有效正整数字符串时，记录 `submitted` 与内容 ID。其他代码或格式交由页面证据核对。该规则参考[官方提交组件](https://lf-fe-creator.douyinstatic.com/obj/douyn-creator-scm-cdn/douyin-creator-content-new/micro/static/js/async/1060.abf5c0f7.js)及[官方文章组件](https://lf-fe-creator.douyinstatic.com/obj/douyn-creator-scm-cdn/douyin-creator-content-new/micro/static/js/async/4301.fe9b29ea.js)，不主动调用平台发布接口，也不从 ID 构造公开地址。接收回执不能证明文章已审核通过或公开发表。

`unknown` 或已记录 `submit_started` 的任务，需要人工核查平台记录后通过 `resolve` 记录依据，确认未提交才可重试。预览不点击正式发布，平台可能自动保存草稿。验收账号的账号名、Cookie、私人目录、内容截图中的账号信息不得加入公开文档。

后续每个平台按同一顺序验收：登录 / 权限 → 标题与正文格式 → 三张正文图及相邻段落 → 封面 → 原生话题与专属选项 → 预览证据 → 一次正式提交回执 → 公开文章标题与链接。分别更新上述表格；平台或运行环境不具备时保留「未验证」，不能以其他平台通过代替。
