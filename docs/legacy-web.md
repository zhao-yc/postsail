# 历史 Web 版本说明

## 当前文章管理入口

`sau_backend.py` 和 `sau_frontend/` 已加入独立维护的文章流程：网页路由 `/articles`、`/api/articles` 与素材 / 发布批次 / 账号子任务 API，以及 `sau article` 客户端。该流程需要安装 `uv pip install -e ".[web]"`，使用现有 SQLite 和网页账号；完整配置及使用方法见[独立多平台文章发布](./articles.md)。

百家号、知乎、今日头条、搜狐号文章首版支持立即发布和可选预览，不支持定时。HTTP 受理和平台审核中均不能直接显示为“已发表”。四平台真实账号验收尚未完成，当前验证范围为离线和隔离流程。

## 历史封装与示例

这套 Web 相关代码主要包括：

- `sau_backend.py`
- `sau_backend/`
- `sau_frontend/`

其中保留了项目过去阶段的封装、示例和部分文档。以下说明针对这些历史部分，不适用于上面的当前文章管理入口。

## 当前定位

- 历史接口作为兼容路径保留；旧文章请求转接当前任务服务
- 作为过去 API / Web 封装思路的参考
- 旧示例和历史参数说明仍需按当前代码核对
- 不承诺和当前 `uploader/`、`sau_cli.py` 的最新实现完全同步

## 为什么单独拆出来说明

当前工程正在整体重构，主线已经切到：

- `uploader/`：核心平台实现
- `sau_cli.py`：CLI 主入口
- `skills/`：面向 agent 的 skill

文章流程在此基础上提供自己的持久化原稿与任务记录，README 介绍当前文章网页入口；其余历史示例不作为新功能的接口契约。

## 如果你仍然想研究这套历史 Web 版本

可以参考这些文件：

- `sau_backend/README.md`
- `sau_frontend/README.md`
- `sau_backend.py`

但请预期：

- 接口契约可能与当前主线不一致
- 平台能力覆盖可能落后于当前 `uploader/`
- 依赖和运行方式可能需要自行排障

## 当前推荐入口

旧版 `examples/upload_video_to_xhs.py` 的个人账号配置 `uploader/xhs_uploader/accounts.ini` 已停止跟踪并保留在本地，公开仓库只提供空白示例。需要研究该旧流程时，先复制 `uploader/xhs_uploader/accounts.example.ini` 为同目录的 `accounts.ini`，再自行填写 Cookie；不要将账号配置提交到公开仓库。当前主线小红书功能仍优先使用 `sau xiaohongshu`。

如果你要使用当前主线能力，优先看：

- `uploader/`
- `sau_cli.py`
- `docs/CLI.md`
- `docs/articles.md`：当前文章 Web、API 与 CLI
- `skills/douyin-upload/SKILL.md`
