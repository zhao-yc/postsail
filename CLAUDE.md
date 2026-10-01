# 项目指引

PostSail（播舟）是开源的多平台内容发布与运营工具，由 Python 后端、`sau` CLI 和 Vue 管理台组成。沿用 `social-auto-upload` 分发包名及已有源码目录，维护时注意兼容已有用户。

开始工作前阅读 [AGENTS.md](./AGENTS.md)，遵守其中的开发原则。使用中文交流、注释和文档；账号会话、密钥、本地配置与数据库不得提交到公开仓库。

- [安装与环境](./docs/install.md)：依赖、浏览器、配置和数据库初始化。
- [CLI 使用](./docs/CLI.md)：以 `sau` 为当前命令入口。
- [架构概览](./README.md#架构概览)：后端、前端和各业务模块的职责。
- [文章管理](./docs/articles.md)与[平台验证记录](./docs/article-platform-verification.md)：文章接口、任务状态及实际验收范围。
- [运营工作台](./docs/operations.md)：互动消息、回复策略、分析与周期报表。
- [历史 Web 接口](./docs/legacy-web.md)：兼容路径和旧示例排障参考。

平台操作可参考仓库 `skills/`；`examples/` 保留单平台排障用途。实现与验证以当前代码和上述文档为准，如实说明尚未验证的平台与环境。
