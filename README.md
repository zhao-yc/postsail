# OmniPost

**OmniPost** 是多平台自媒体内容自动发布工具：支持将 **视频 / 图文** 一键发布到 `抖音`、`Bilibili`、`小红书`、`快手`、`视频号`、`百家号`、`今日头条`、`搜狐号`、`知乎`、`TikTok` 等平台，并提供 **Web 管理台**、**统一 CLI（`sau`）** 与 **示例脚本** 三种使用方式。

> 本仓库基于开源项目 [dreammis/social-auto-upload](https://github.com/dreammis/social-auto-upload) 二开。感谢原作者与社区贡献者。

<img src="media/show/tkupload.gif" alt="demo" width="800"/>

## 赞助商

<table width="100%">
  <tr>
    <td width="25%" align="center" valign="middle">
      <a href="https://api.rehat.cn/">
        <strong>Rehat API</strong>
      </a>
    </td>
    <td width="75%" align="left" valign="middle">
      <a href="https://api.rehat.cn/">Rehat API</a>：稳定好用的 AI 大模型中转站。一套接口打通 Claude、GPT、Gemini、DeepSeek、通义等主流模型，兼容 OpenAI 协议，OpenClaw、Claude Code、Codex、Cherry Studio 等工具可直接接入。按量计费、延迟低、适合日常开发与自媒体 Agent 场景。
      <a href="https://api.rehat.cn/">https://api.rehat.cn/</a>
    </td>
  </tr>
</table>

---

## 目录

- [赞助商](#赞助商)
- [功能特性](#功能特性)
- [架构概览](#架构概览)
- [环境要求](#环境要求)
- [安装](#安装)
- [快速开始](#快速开始)
- [平台能力](#平台能力)
- [配置说明](#配置说明)
- [文档索引](#文档索引)
- [AI Agent](#ai-agent)
- [免责声明](#免责声明)
- [贡献](#贡献)
- [致谢](#致谢)
- [许可证](#许可证)

## 功能特性

- **多平台发布**：抖音、B 站、小红书、快手、视频号、百家号、今日头条、搜狐号、知乎、TikTok 等
- **视频 + 图文**：部分平台支持图文 / 文章（见能力表）
- **账号与 Cookie 管理**：Web 扫码 / 导入 Cookie，CLI `login` / `check`
- **定时发布**：多数平台支持（以各平台后台能力为准）
- **统一 CLI**：`sau <platform> <action>`，便于脚本化与 Agent 调用
- **可扩展 uploader**：每个平台独立模块，便于二开接入新平台

为什么还需要这种项目：上传是高频、重复、流程固定的工作。与其每次让通用 Browser Agent 临场解析页面，不如把已验证的发布链路固化成脚本 / CLI / Web 任务。

## 架构概览

| 部分 | 说明 |
| --- | --- |
| `sau_backend.py` | Flask API：账号、素材、发布任务 |
| `sau_frontend/` | Vue3 + Element Plus 管理台（账号 / 素材 / 发布中心） |
| `uploader/*` | 各平台 Playwright / 专用运行时上传实现 |
| `sau_cli.py` | 统一 CLI 入口（安装后命令为 `sau`） |
| `examples/` | 单平台登录 / 上传示例脚本 |
| `skills/` | 面向 Agent 的平台 Skill（抖音 / 快手 / 小红书 / B 站） |
| `db/` | SQLite 账号与文件元数据 |

## 环境要求

- Python **3.10+**（推荐 3.11）
- Node.js **18+**（仅使用 Web 前端时需要）
- Windows / macOS / Linux
- 推荐使用 [`uv`](https://github.com/astral-sh/uv) 管理依赖

## 安装

详细步骤见：[安装说明](./docs/install.md) · [更新说明](./docs/update.md)

### 1. 克隆与 Python 依赖

```bash
git clone https://github.com/rehatRobot/omnipost.git
cd omnipost

uv venv
# Windows
.venv\Scripts\activate
# Linux / macOS
# source .venv/bin/activate

uv pip install -e .
```

安装后可直接使用 `sau` 命令（CLI 入口名暂仍为上游的 `sau`，后续可再改为 `omnipost`）。

### 2. 浏览器驱动

主线使用 `patchright`（兼容 Playwright API）：

```powershell
# Windows 国内镜像示例
$env:PLAYWRIGHT_DOWNLOAD_HOST="https://npmmirror.com/mirrors/playwright"
patchright install chromium
```

部分平台 / 示例仍可能使用 `playwright`，可按需补充：

```bash
playwright install chromium
```

### 3. 配置与数据库

```bash
# 复制配置（按需修改本地 Chrome 路径、调试开关等）
cp conf.example.py conf.py   # Windows 可用 copy

python db/createTable.py
```

**不要**把 `conf.py`、`cookies/`、`cookiesFile/`、`database.db` 提交到公开仓库。

### 4. Web 前后端（可选）

```bash
# 后端
python sau_backend.py
# 默认 http://localhost:5409

# 前端
cd sau_frontend
npm install
npm run dev
# 默认 http://localhost:5173
```

## 快速开始

### 方式 A：Web 发布中心

1. 启动后端 + 前端  
2. 打开「账号管理」添加并登录平台账号  
3. 在「素材管理」上传视频 / 封面  
4. 在「发布中心」选择平台、填写标题正文、发布或预览（dry-run）

适合日常运营与多账号可视化管理。

### 方式 B：CLI（当前已接入平台）

```bash
sau douyin login --account <account_name>
sau douyin check --account <account_name>
sau douyin upload-video --account <account_name> --file videos/demo.mp4 --title "示例标题" --desc "示例简介"
sau douyin upload-note --account <account_name> --images videos/1.png videos/2.png --title "图文标题" --note "图文正文"

sau kuaishou login --account <account_name>
sau kuaishou upload-video --account <account_name> --file videos/demo.mp4 --title "示例标题"

sau xiaohongshu login --account <account_name>
sau xiaohongshu upload-note --account <account_name> --images videos/1.png videos/2.png --title "图文标题" --note "正文"

sau bilibili login --account <account_name>
sau bilibili upload-video --account <account_name> --file videos/demo.mp4 --title "示例标题" --tid 249
```

更多说明：[CLI 使用说明](./docs/CLI.md)

约定简述：

- `account_name` 是你自定义的账号名，对应 `cookies/<platform>_uploader/<account_name>.json`
- 视频元数据常用：`title + desc + tags`
- 图文元数据常用：`title + note + tags`
- B 站首次相关命令会自动准备 `biliup`；登录建议在本地真实终端执行

### 方式 C：examples 脚本

适合调试单平台 uploader（头条 / 搜狐 / 知乎 / 百家号图文等尚未全部 CLI 化时，优先用此方式或 Web）：

```bash
# 登录示例
python examples/get_toutiao_cookie.py
python examples/get_sohu_cookie.py
python examples/get_zhihu_cookie.py

# 发布示例（按脚本内注释修改路径与文案）
python examples/upload_article_to_toutiao.py
python examples/upload_article_to_sohu.py
python examples/upload_article_to_zhihu.py
python examples/upload_article_to_baijiahao.py
```

抖音 / 快手 / 小红书 / B 站优先用 `sau ...`，不必再走旧示例主路径。

## 平台能力

| 平台 | 登录 | 视频 | 图文/文章 | 定时 | CLI | Skill | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 抖音 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | CLI/Skill 最完整 |
| Bilibili | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | 依赖 `biliup` 运行时 |
| 小红书 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | 浏览器自动化 |
| 快手 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | 浏览器自动化 |
| 视频号 | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ | `tencent_uploader` |
| 百家号 | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | Web / examples |
| 今日头条 | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | 图文为「发文章」，非微头条 |
| 搜狐号 | ✅ | ❌ | ✅ | ✅ | ❌ | ❌ | 仅图文；标题 5–72 字；封面 **大于 450×300**，jpg/jpeg/png，≤10MB |
| 知乎 | ✅ | ❌ | ✅ | ✅ | ❌ | ❌ | 第一期仅文章 |
| TikTok | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ | 示例偏 Chrome 版实现 |

平台后台改版、风控、账号权限（如实名）会导致自动化失效，属正常现象，需要跟进维护选择器与流程。

## 配置说明

- 配置模板：[`conf.example.py`](./conf.example.py) → 复制为 `conf.py`
- Cookie 目录：`cookies/`（CLI / 示例）与 `cookiesFile/`（Web 账号）
- 素材目录：常见为 `videoFile/`（以后端实际配置为准）
- 日志：`logs/`

开源或分享仓库前请确认敏感文件已被忽略，可参考 [`.gitignore`](./.gitignore)。

## 文档索引

| 文档 | 内容 |
| --- | --- |
| [docs/install.md](./docs/install.md) | 安装与环境 |
| [docs/update.md](./docs/update.md) | 更新说明 |
| [docs/CLI.md](./docs/CLI.md) | `sau` CLI |
| [docs/agent-bootstrap.md](./docs/agent-bootstrap.md) | 交给 AI Agent 的启动提示词 |
| [docs/legacy-web.md](./docs/legacy-web.md) | 历史 Web 说明 |
| [skills/*/SKILL.md](./skills) | 各平台 Agent Skill |

## AI Agent

如果你把本仓库交给 OpenClaw、Codex、Claude Code 等使用：

1. 先发送仓库 + [Agent Bootstrap Prompt](./docs/agent-bootstrap.md)  
2. 优先让 Agent 走 `uv` + `sau` + `skills/`  
3. 先验证：`douyin` / `kuaishou` / `xiaohongshu` / `bilibili` 四个 CLI 入口  

相关 Skill：

- [Douyin](./skills/douyin-upload/SKILL.md)
- [Kuaishou](./skills/kuaishou-upload/SKILL.md)
- [Xiaohongshu](./skills/xiaohongshu-upload/SKILL.md)
- [Bilibili](./skills/bilibili-upload/SKILL.md)

## 免责声明

- 本项目仅供学习、研究与个人效率提升使用。  
- 使用自动化发布可能违反部分平台用户协议，存在账号限制、验证码、功能不可用等风险，**后果由使用者自行承担**。  
- 请勿用于垃圾信息、违规内容分发或其他违法用途。  
- 平台页面与接口随时变更，不保证某一功能长期可用。

## 贡献

欢迎 Issue / PR：

1. Fork 本仓库  
2. 新建分支：`feature/xxx` 或 `fix/xxx`  
3. 提交清晰的变更说明  
4. 发起 Pull Request  

建议：改动平台自动化时附上复现步骤、日志片段（`logs/`）与是否 dry-run。

## 致谢

- 原项目：[dreammis/social-auto-upload](https://github.com/dreammis/social-auto-upload)
- B 站上传能力基于 [biliup](https://github.com/biliup/biliup) 的接入与封装
- 所有提交 Issue、PR 与反馈的贡献者

## 许可证

本项目采用 [MIT License](./LICENSE)。

使用或二次发布时，请保留许可证与版权声明，并保留对上游项目与 `biliup` 的致谢信息。
