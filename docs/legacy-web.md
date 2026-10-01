# 历史 Web 接口与示例

当前 Web 后端为仓库根目录的 `sau_backend.py`，管理台位于 `sau_frontend/`。安装与启动见[安装说明](./install.md)，模块职责见[架构概览](../README.md#架构概览)。原 `sau_backend/README.md` 的历史接口说明已合并至本文。

当前文章能力、API、CLI 和任务状态见[独立多平台文章发布](./articles.md)，平台依据与实际验收范围见[平台验证记录](./article-platform-verification.md)。旧文章请求已转接任务服务，HTTP 受理不能作为平台已发表的依据。

## 兼容接口索引

这些路径保留供已有 Web 客户端使用。以下只是排障索引；完整参数、校验和返回结果以当前 [sau_backend.py](../sau_backend.py) 为准。

| 接口 | 用途与关键参数 |
| --- | --- |
| `POST /upload` | 通过表单字段 `file` 上传素材，返回保存后的文件名；素材存入仓库根目录 `videoFile/`。 |
| `GET /login` | `id` 为账号名，`type` 为平台标识；使用 SSE 推送登录进度与二维码。 |
| `GET /getValidAccounts` | 逐个校验账号会话，返回可用状态；账号多时可能较慢。 |
| `POST /postVideo` | 使用 JSON 的 `fileList`、`accountList`、`type`、`title`、`tags` 等字段提交发布；`tags` 为不带 `#` 的列表。 |

视频定时相关字段为 `enableTimer`、`videosPerDay`、`dailyTimes`、`startDays`，其组合及平台支持情况须核对当前实现。历史文档曾用 `file_list`、`account_list` 和下划线定时参数描述内部函数，不能直接作为 HTTP 请求字段。`category` 的含义也依赖平台，不能统一解释为原创标记。

## 数据与配置

- `db/database.db`：账号与素材元数据；已有用户更新时保留数据库。
- `cookiesFile/`：Web 账号会话；`cookies/`：CLI 与示例会话。
- `videoFile/`：Web 上传素材；文章数据与备份要求见[文章文档](./articles.md)。
- `conf.py`：本地配置；浏览器选择与配置示例见[安装说明](./install.md)。

上述用户数据和个人配置不得提交到公开仓库。

## 历史示例

`examples/` 保留单平台登录、上传与排障脚本，部分历史参数和平台页面行为可能落后于当前实现。新功能优先使用 [sau CLI](./CLI.md) 和对应的仓库 `skills/`，旧示例不作为当前接口契约。

旧版 `examples/upload_video_to_xhs.py` 使用专用 API 签名流程，个人配置 `uploader/xhs_uploader/accounts.ini` 不纳入版本控制。研究该流程时，先复制 `uploader/xhs_uploader/accounts.example.ini` 为同目录的 `accounts.ini`，自行填写 Cookie；当前主线小红书入口为 `sau xiaohongshu`。
