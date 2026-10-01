# 安装说明

项目名称为 **PostSail 播舟**，公开仓库为 [zhao-yc/postsail](https://github.com/zhao-yc/postsail)。CLI 入口 `sau`、Python 分发包名 `social-auto-upload`、`OMNIPOST_*` 配置项和源码目录名称继续兼容既有使用方式。

这个文档分成两部分：

- `For Humans`：给正常使用仓库的开发者、创作者、CLI 用户看
- `For AI Agents`：给 OpenClaw、Codex、Claude Code 一类 agent 看

如果你是“正在使用 agent 客户端的人”，想先给 agent 一段启动提示词，而不是直接阅读下面的执行细节，先看：

- [Agent Bootstrap Prompt](./agent-bootstrap.md)

## For Humans

### 1. 克隆项目

```bash
git clone https://github.com/zhao-yc/postsail.git
cd postsail
```

### 2. 创建虚拟环境

推荐使用 `uv`：

Windows PowerShell：

```powershell
uv venv
.venv\Scripts\activate
```

Linux / macOS：

```bash
uv venv
source .venv/bin/activate
```

### 3. 安装主线依赖

当前主线依赖已经放到 `pyproject.toml`，推荐直接执行：

```bash
uv pip install -e .
```

安装完成后，会注册 `sau` 命令。

需要运行 Web 后端或本机文章发布服务时，安装 Web 可选依赖（包含 Flask、Playwright）：

```bash
uv pip install -e ".[web]"
```

只在调用端使用 `sau article` 访问另一个已运行的服务时，基础安装即可，无需 Flask。

### 4. 安装 patchright Chromium

当前主线使用 `patchright` 驱动浏览器。

国内用户推荐先指定镜像，再安装 Chromium。

Windows PowerShell：

```powershell
$env:PLAYWRIGHT_DOWNLOAD_HOST="https://npmmirror.com/mirrors/playwright"; patchright install chromium
```

Linux / macOS：

```bash
PLAYWRIGHT_DOWNLOAD_HOST="https://npmmirror.com/mirrors/playwright" patchright install chromium
```

抖音、B站、百家号、今日头条、微博、知乎、企鹅号、搜狐号的文章适配器使用 Playwright，按显式 `LOCAL_CHROME_PATH` → 系统 Chrome → 已安装 Playwright Chromium 选择浏览器。显式路径无效会提示修正；只有未配置路径且系统 Chrome 未安装时才回退 Chromium。需要 Chromium 回退时，在运行后端的机器执行：

```bash
python -m playwright install chromium
```

文章的 Playwright Chromium 与视频的 Patchright Chromium 分别安装。Linux 上若浏览器提示系统库缺失，请按 Playwright 的报错安装对应系统依赖；不要把某台维护者电脑的浏览器路径写进公共配置。

### 5. 配置 conf.py

复制一份配置：

```bash
cp conf.example.py conf.py
```

Windows 也可以直接手动复制并重命名。

当前通常还会用到这些配置项：

- `LOCAL_CHROME_PATH`
- `LOCAL_CHROME_HEADLESS`
- `BILIBILI_TERMINAL_COMMAND`：Linux 上打开 B站扫码登录终端的参数列表，例如 `["gnome-terminal", "--"]`
- `DEBUG_MODE`
- `ARTICLE_BROWSER_HEADLESS`：文章浏览器是否隐藏
- `ARTICLE_RENDER_FONT`：表格、代码截图字体，部署环境需有对应中文字体
- `ARTICLE_PREVIEW_SECONDS`：文章预览截图后保留浏览器秒数，默认 0
- `ARTICLE_WORKER_ENABLED`：是否启用后端内置的串行文章执行器

`XHS_SERVER` 目前只和小红书旧流程相关。

### 6. 验证 CLI 是否可用

```bash
sau --help
sau douyin --help
sau kuaishou --help
sau xiaohongshu --help
sau bilibili --help
sau article --help
```

如果命令找不到，优先确认：

- 当前虚拟环境是否已激活
- 是否执行过 `uv pip install -e .`

### 7. 抖音主线示例

```bash
sau douyin login --account <account_name>
sau douyin check --account <account_name>
sau douyin upload-video --account <account_name> --file videos/demo.mp4 --title "示例标题" --desc "示例简介"
sau douyin upload-note --account <account_name> --images videos/1.png videos/2.png --title "图文标题" --note "图文正文"
```

### 8. 快手主线示例

```bash
sau kuaishou login --account <account_name>
sau kuaishou check --account <account_name>
sau kuaishou upload-video --account <account_name> --file videos/demo.mp4 --title "示例标题" --desc "示例简介"
sau kuaishou upload-note --account <account_name> --images videos/1.png videos/2.png videos/3.png --title "图文标题" --note "图文正文"
```

### 9. 小红书主线示例

```bash
sau xiaohongshu login --account <account_name>
sau xiaohongshu check --account <account_name>
sau xiaohongshu upload-video --account <account_name> --file videos/demo.mp4 --title "示例标题" --desc "示例简介"
sau xiaohongshu upload-note --account <account_name> --images videos/1.png videos/2.png videos/3.png --title "图文标题" --note "图文正文"
```

### 10. Bilibili 主线示例

```bash
sau bilibili login --account <account_name>
sau bilibili check --account <account_name>
sau bilibili upload-video --account <account_name> --file videos/demo.mp4 --title "示例标题" --desc "示例简介" --tid 249
```

补充说明：

- `creator` 之类的名字只是示例值，真正传的是用户自定义的 `account_name`
- 一个 `account_name` 对应一个账号文件，可以准备多个账号并发使用
- 浏览器平台统一元数据约定：
- 视频使用 `title + desc + tags`
- 图文使用 `title + note + tags`
- 用户不需要手动安装 `biliup`
- 首次运行 Bilibili 相关命令时，程序会自动下载 `biliup`
- 后续运行会自动检查上游 release 并自动更新
- Bilibili 登录建议由用户自己在本地真实终端里执行；如果终端里的二维码显示不完整，可直接打开当前目录下的 `qrcode.png` 扫码
- 网页登录在 Windows 打开新控制台，macOS 使用 Terminal；Linux 优先使用配置的 `BILIBILI_TERMINAL_COMMAND`，否则尝试 `x-terminal-emulator`
- 无图形终端或浏览器的后端可以在有界面的电脑完成登录，再通过网页「账号管理」导入会话 JSON；终端不可用时界面会提示导入，不会把启动失败视为登录成功
- B站文章兼容标准 Playwright `storage_state` 及 `biliup` 的 `cookie_info.cookies`；文章只在内存中转换 `biliup` 会话，不覆盖视频上传需要的原始 token 字段
- 如果国内网络访问 GitHub Release 较慢，可先用 `https://gh-proxy.com/` 或 `https://gh-proxy.org/` 辅助访问对应 release 地址排障
- 示例：
  - `https://gh-proxy.org/https://github.com/biliup/biliup/releases/download/v1.1.29/biliupR-v1.1.29-aarch64-linux.tar.xz`

### 11. 独立文章与网页管理

后端使用现有 SQLite 数据库，文章结构通过增量建表添加，不要删除或重建已有数据库。新安装按[README 的配置与数据库步骤](../README.md#3-配置与数据库)初始化。

```bash
uv pip install -e ".[web]"
python sau_backend.py
```

前端在另一个终端启动：

```bash
cd sau_frontend
npm install
npm run dev
```

网页打开「账号管理」登录平台，再进入「文章管理」（路由 `/articles`，默认 `http://localhost:5173/#/articles`）编辑原稿、上传图片、选择平台并查询各账号任务。编辑器里的[本地开发入口](./local-development.md)默认使用 5175 端口，实际地址以启动日志为准。

```bash
sau article accounts --json
sau article import --file ./draft/article.md --title "示例教程" --cover ./draft/cover.png --json
sau article publish ARTICLE_ID --targets ./targets.json --preview --idempotency-key draft-preview-01 --json
sau article status BATCH_ID --wait --json
```

服务地址通过 `--server` 或 `OMNIPOST_API_URL` 配置。八平台文章默认立即发布、预览可选，定时请求明确不支持。抖音完整真实预览已通过，正式发布已取得明确提交回执，公开文章已现场核实；本次未验收真实原生话题或声明，其他七平台缺少验收账号。后续实际结果集中记录于[文章平台验证记录](./article-platform-verification.md)。完整 API、CLI、目标文件及备份迁移见[独立多平台文章发布](./articles.md)。

微博新增账号类型为 `10`，企鹅号为 `11`，原有编号保持兼容；企鹅号与微信视频号（类型 `2`）使用不同入口和账号记录。网页登录需手动完成认证，导入会话还会校验 JSON 结构、目标域名和真实登录状态；Cookie 字段存在不能证明有文章权限。普通平台导入 Playwright `storage_state` JSON（含 `cookies`、`origins`），B站也可导入 `biliup` JSON，文件上限为 5MB。校验失败不会覆盖已有凭据。账号 API 不返回 Cookie 内容，会话文件不能提交公开仓库。

## For AI Agents

如果你是一个可执行命令的 agent，请优先按下面顺序处理：

1. 先假设仓库根目录就是当前工作目录
2. 优先使用 `uv` 管理环境，不要默认回退到旧的 `requirements.txt`
3. 安装命令优先使用：

```bash
uv pip install -e .
```

运行文章后端或网页服务时改用 `uv pip install -e ".[web]"`；只调用远程文章服务则保持基础安装。

4. 如需浏览器驱动，优先使用：

Windows PowerShell：

```powershell
$env:PLAYWRIGHT_DOWNLOAD_HOST="https://npmmirror.com/mirrors/playwright"; patchright install chromium
```

Linux / macOS：

```bash
PLAYWRIGHT_DOWNLOAD_HOST="https://npmmirror.com/mirrors/playwright" patchright install chromium
```

5. 安装完成后，优先检查：

```bash
sau --help
sau douyin --help
sau kuaishou --help
sau xiaohongshu --help
sau bilibili --help
sau article --help
```

6. 如果用户的目标是抖音或快手的登录、cookie 校验、视频上传、图文上传，优先走 CLI：

```bash
sau douyin login
sau douyin check
sau douyin upload-video
sau douyin upload-note

sau kuaishou login
sau kuaishou check
sau kuaishou upload-video
sau kuaishou upload-note

sau xiaohongshu login
sau xiaohongshu check
sau xiaohongshu upload-video
sau xiaohongshu upload-note

sau bilibili login
sau bilibili check
sau bilibili upload-video
```

7. 如果用户明确在使用 skill 系统，再引导其阅读：

- `skills/douyin-upload/SKILL.md`
- `skills/douyin-upload/references/cli-contract.md`
- `skills/kuaishou-upload/SKILL.md`
- `skills/kuaishou-upload/references/cli-contract.md`
- `skills/xiaohongshu-upload/SKILL.md`
- `skills/xiaohongshu-upload/references/cli-contract.md`
- `skills/bilibili-upload/SKILL.md`
- `skills/bilibili-upload/references/cli-contract.md`

### 对 agent 的额外说明

- 当登录流程生成本地二维码图片时，不要只把图片路径发给用户
- 这类二维码图片本身就是给用户扫码的，agent 应优先直接展示/发送本地图片给用户扫码
- 如果环境支持查看本地图片，优先用查看图片能力把二维码展示出来；路径只作为补充信息
- Bilibili 登录当前不建议 agent 在非交互环境里直接代跑
- 正确做法是让用户自己在本地终端执行 `sau bilibili login --account <name>`；如果二维码显示不完整，再提示用户打开 `qrcode.png`
- `requirements.txt` 目前是历史兼容文件，不是主安装入口
- `uploader/` 是核心实现目录
- `sau_cli.py` 是当前 CLI 主入口
- `docs/legacy-web.md` 是历史 Web 版本说明，不保证当前可用
- 当前文章管理 `/articles` 和 `/api/articles` 是独立维护的入口，见 `docs/articles.md`；`docs/legacy-web.md` 区分这些入口与历史封装
- Bilibili 首次运行时可能自动下载 `biliup`
