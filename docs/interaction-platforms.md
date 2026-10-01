# 互动平台接入与验证范围

互动工作台通过现有账号管理中的账号与登录文件运行。发布、统计和互动是独立能力，不能根据“支持发布”推断某平台支持评论或私信。所有新增适配器均有实际读取与回复实现；缺少登录、授权或明确回执时会报错，不使用空列表伪装成功。

## 当前能力

| 平台 | 评论读取 | 评论文字回复 | 单人文字私信 | 进入私信欢迎语 |
| --- | --- | --- | --- | --- |
| 抖音 | 已只读验证自己作品、主楼与子评论分页 | 已实现，未实际发送验收 | 官方回调接收与回复；另需开放平台授权，未实测 | 官方进入会话事件触发；另需授权，未实测 |
| 视频号 | 已实现，需真实账号验证 | 已实现，需真实账号验证 | 已实现助手历史快照与回复，需真实账号验证 | 未接入 |
| 小红书私信版 | 未接入 | 未接入 | 已实现普通账号 `/chat` 网页的会话、历史分页与回复，需真实账号验证 | 未接入 |
| B站 | 已实现自己作品及完整子评论分页，需真实账号验证 | 已实现，需真实账号验证 | 已实现已有会话及历史分页与回复，需真实账号验证 | 未接入 |
| 快手、百家号、头条、搜狐、知乎 | 未接入 | 未接入 | 未接入 | 未接入 |

2026-10-01 在 macOS 上使用项目现有抖音登录文件完成了只读验证：账号范围按作品连续采集；一条图片主评论及两条楼内回复；子评论的主楼关系；含表情回复的唯一 DOM 定位。未发送、删除评论或私信。其他平台没有可用测试账号，不能把 mock 测试通过解释成这些平台已经完成端到端验收。Windows、Linux 及容器环境尚未验证本模块。

`list_capabilities(account=None)` 返回理论实现范围；传入账号后只读检查本地登录文件和抖音单独授权配置。`available` 表示该读取流程取得真实验证证据，`unverified` 表示有实现但尚缺该流程的真实验收，`needs_login` 表示缺少登录或官方授权，`unsupported` 表示尚未实现。没有平台的真实发送操作被标记为 `available`。

## 适配器契约

入口位于 `utils/interactions/adapters/__init__.py`。平台标识沿用现有账号类型：抖音 `douyin`、视频号 `tencent`、小红书 `xiaohongshu`、B站 `bilibili`。

```python
adapter = get_adapter(account["platform"])
batch = adapter.fetch(account, cursor=None, kind="comment", item_id=None, limit=50)
# batch = {"items": [...], "cursor": "下一页游标或 None", "hasMore": False}
result = adapter.send_reply(account, message, "回复文本", "持久化幂等键")
# 只有明确回执才返回 {"text": "回复文本", "confirmed": True, "platformReplyId": "可选平台ID"}
```

账号提供 `id`、`platform`、`name`、`cookie_path`。消息提供 `platformMessageId`、`kind`、`threadId`、`parentId`、`itemId`、`itemTitle`、作者信息、文本、带时区时间、入站或出站方向，以及内部路由信息 `raw`。抖音欢迎事件使用独立的 `kind="welcome"`，不等同关注事件，也不由首次私信推断。

平台不提供精确父消息 ID 时，子评论 `parentId` 指向其主楼，`threadId` 保留主楼 ID。抖音图片评论显示占位文字，目前不下载图片；媒体私信、群聊、撤回和未知类型不作为文字自动回复目标。

能力结构明确区分操作：

```json
{
  "platform": "douyin",
  "kinds": ["comment", "private", "welcome"],
  "fetchableKinds": ["comment"],
  "operations": {
    "comment": {"fetch": "available", "reply": "unverified", "transport": "browser"},
    "private": {"fetch": "needs_login", "reply": "unverified", "transport": "webhook"},
    "welcome": {"fetch": "needs_login", "reply": "unverified", "transport": "webhook"}
  }
}
```

`fetchableKinds` 是可轮询的类型。抖音私信和欢迎事件从签名回调进入，调用 `fetch(kind="private")` 或 `fetch(kind="welcome")` 会明确报 `webhook_only`，不会返回虚假的“没有消息”。

## 登录、浏览器与凭据

评论与网页私信复用账号管理保存的登录态。B站同时兼容 Playwright 与 biliup 的登录文件，发送需要 `SESSDATA` 与 `bili_jct`；其他浏览器适配器需要 Playwright 格式。HTTP 请求按域名过滤凭据、保留 TLS 验证、不跟随重定向，发送请求不自动重试。

抖音和小红书沿用 `conf.py` 的 `LOCAL_CHROME_PATH`、`LOCAL_CHROME_HEADLESS` 以及项目浏览器选择逻辑，配置项见 `conf.example.py`。没有写死维护者的浏览器路径。浏览器不可用时会提示配置系统 Chrome；`requests`、`patchright` 由项目主线 `pyproject.toml` 声明，无额外签名服务依赖。安装与浏览器准备按 `docs/install.md` 和主 README 执行。

账号、Cookie、密钥及授权文件不能进入公开仓库。内部 `raw` 只保留会话双方、平台消息、主楼与翻页定位字段，业务层按白名单持久化；公共消息接口不返回 `raw`。不要把整个平台响应、HTTP 请求或 Cookie 复制到日志中。

## 抖音官方私信与欢迎语配置

普通创作者登录 Cookie 不等于开放平台私信授权。官方接口需要具备 `im.direct_message` 能力的应用与经营账号及有效 `business_token`。官方进入私信事件文档目前说明新增小程序不能直接开通对应能力，特殊情况需要联系平台运营；存量应用仍需申请权限。缺少权限时，本项目不能以网页 Cookie 代替授权。

在账号登录文件同目录创建 `<账号文件名去掉.json>.interactions.json`。下面仅是配置格式，所有值均为占位符；不要复制真实凭据进文档或版本控制。

```json
{
  "client_key": "YOUR_CLIENT_KEY",
  "client_secret": "YOUR_CLIENT_SECRET",
  "open_id": "AUTHORIZED_ACCOUNT_OPEN_ID",
  "business_token": "YOUR_BUSINESS_TOKEN",
  "scopes": ["im.direct_message"]
}
```

`scopes` 可省略；若填写且缺少 `im.direct_message`，账号私信与欢迎语能力会显示需要授权，发送会被拒绝。配置文件存在只说明已配置，不能证明令牌仍有效或平台已授予能力。令牌获取、续期和平台权限申请由账号运营者完成。

将公网 HTTPS 回调指向服务的 `/api/interactions/webhooks/douyin/<account_id>`，在开放平台订阅 `im_receive_msg`、`im_send_msg` 及需要时的 `im_enter_direct_msg`。验证必须使用请求原始字节和 `X-Douyin-Signature`；签名为 `SHA1(client_secret + 原始请求体)`。验证成功后，适配器校验应用标识、账号归属与单人会话，支持官方 `content` 对象及 JSON 字符串格式；`verify_webhook` 返回原 `challenge`。

普通文字回复使用 `im_reply_msg`，必须绑定收到的 `server_message_id` 与 `conversation_short_id`，仅在 24 小时窗口内提交。欢迎语使用独立事件 `im_enter_direct_msg`，必须在进入会话事件发生后 30 秒内提交，向该事件的原接收会话发送。官方还限制同一用户进私场景的日次数、小时间隔及每次消息数；最终以平台限制为准。本实现每条事件只提交一条文字，业务层幂等控制回调重复与策略重入。

`new_follow_action` 是关注事件，本模块不将它转换成欢迎语。没有官方进私信事件的账号无法开启这个自动触发流程。用户在抖音官方互动经营工作台已经启用策略时，也可能与开放 API 互斥，需要在平台核对配置。

## 精确定位与不确定结果

抖音主评论和子评论均监听页面真实 GET。已带网页签名的评论请求不改写重放，而通过原生列表滚动或“查看回复”触发分页。回复根据原平台加密 ID 找到当前数据，再按作者、时间、完整文本、图片数与层级唯一确定 DOM 行；表情使用图片 `alt`，回复前缀单独去除。只操作该行的回复输入框与发送按钮。多条视觉相同评论、游标失效或布局改版时停止发送，绝不回退到作品顶层发表评论框。

小红书先核对现有会话双方和目标消息，再使用该会话的真实输入框按一次 Enter，之后以新增出站平台消息 ID、文案及方向确认。历史目标会继续读取历史页；一次查找最多 50 页会话及 50 页历史。抖音缺少旧页游标的旧消息可查找最多 50 页主评论；超出范围需要重新同步或到平台处理。

视频号私信接口返回历史快照，本实现按该快照分页，无法宣称它是所有历史消息的完整归档。平台可自行限制可见历史。B站与视频号没有本次实机账号，接口字段、签名或权限变化可能导致报错，需要使用真实账号再验收。

`InteractionAdapterError(code, 中文说明, retryable=False)` 向服务明确传递问题。发送发生后超时、回执缺少业务码、布尔值被用作业务码、回执结构变化或不能确认新增消息，均为 `send_unknown`，不可自动重试。服务将消息保留为待核查，核对平台后才能登记结果。只有明确未提交或明确拒绝的错误才可登记失败。

## 来源与测试

实现依据一级来源，未依赖关闭维护的第三方服务；接口知识和选择器按本项目契约独立实现。

- [抖音开放平台评论列表](https://open.douyin.com/platform/resource/docs/openapi/interaction-management/comment-management-user/comment-list)、[评论回复](https://open.douyin.com/platform/resource/docs/openapi/interaction-management/comment-management-user/video-comment-reply)。当前网页评论 API 与 DOM 另由登录后的创作者助手只读实测。
- [抖音事件列表](https://developer.open-douyin.com/docs/resource/zh-CN/dop/develop/webhooks/event-list)、[回调验证](https://developer.open-douyin.com/docs/resource/zh-CN/dop/develop/webhooks/summarize)、[私信消息事件](https://developer.open-douyin.com/docs/resource/zh-CN/mini-app/develop/server/reach-marketing/instant-message/private-message/private-msg-webhook)、[进入私信事件](https://developer.open-douyin.com/docs/resource/zh-CN/mini-app/develop/server/reach-marketing/instant-message/private-message/enter-direct-msg-webhook)、[发送私信](https://developer.open-douyin.com/docs/resource/zh-CN/mini-app/develop/server/reach-marketing/instant-message/private-message/send-message)。
- [视频号原作者 wx_video_sdk](https://github.com/dsxksss/wx_video_sdk)：创作者助手的认证、作品、评论与私信接口。
- [小红书原作者 creatorhub](https://github.com/3441293738/creatorhub)：`app/browser/xhs_im.py` 的会话/历史接口与 `xhs_dm.py` 的网页输入框及提交行为。
- [B站接口原项目评论列表](https://github.com/pskdje/bilibili-API-collect/blob/main/docs/comment/list.md)、[评论操作](https://github.com/pskdje/bilibili-API-collect/blob/main/docs/comment/action.md)、[私信](https://github.com/pskdje/bilibili-API-collect/blob/main/docs/message/private_msg.md)。这些是社区原项目接口资料，不是 B站官方支持承诺。

离线测试不连接外部平台：

```bash
python -m unittest tests.test_interaction_adapters -v
```

测试覆盖凭据域隔离、游标异常、完整子评论页、入站方向与撤回过滤、官方签名与账号归属、欢迎事件和时间窗口、模糊行拒绝发送、只提交一次、未知回执不重试，以及经真实 `InteractionService` 入库并重新加载内部路由后，四个平台实际 `send_reply` 发往替身传输层的目标 ID 与会话核对。
