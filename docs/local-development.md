# 编辑器里的本地开发入口

VS Code、Codex 和终端共用 `.codex/scripts/dev.sh`，管理 Web 后端和前端。
这些入口适用于 macOS、Linux，以及在 WSL 中打开的 Windows 项目。
原生 Windows 的手动启动方式仍见 [安装说明](./install.md)。

## 首次准备

先按 [安装说明](./install.md) 创建项目 `.venv`、配置 `conf.py` 和初始化数据库。
当前 Web 后端还需要 Web 扩展和以下依赖，先在项目根目录安装：

```bash
uv pip install -e '.[web]'
uv pip install playwright==1.58.0 xhs==0.2.13 pillow==11.2.1
```

然后在 `sau_frontend` 执行 `npm install`。上述补充依赖版本已在本次 macOS 环境验证。
脚本默认使用项目 `.venv/bin/python`，不会自动安装依赖，也不会重新创建数据库。
Linux / WSL 还需要 `bash`、`ps`、`lsof` 和 `tail`；
Ubuntu / Debian 可用 `sudo apt install lsof` 补充端口检查工具。

编辑器没有加载 Node 环境时，脚本会尝试已有的 nvm 默认版本或 fnm 当前版本。
也可设置 `OMNIPOST_NODE_BIN` 为 Node 可执行文件所在目录，或设置 `OMNIPOST_PYTHON`
为已有 Python 环境中解释器的绝对路径。配置个人路径时使用本地环境变量，不提交到仓库。

## VS Code

通过「终端 → 运行任务」选择以下任务；`Ctrl+Shift+B` / macOS 的 `Cmd+Shift+B`
也可直接运行默认的「PostSail：启动全部」。

| 任务 | 用途 |
| --- | --- |
| PostSail：启动全部 | 启动或复用后端和前端 |
| PostSail：启动后端 | 仅管理后端 |
| PostSail：运行前端 | 仅管理前端 |
| PostSail：停止全部 | 停止本项目的前后端 |
| PostSail：查看状态 | 检查端口、进程归属和 HTTP 响应 |
| PostSail：后端日志 / 前端日志 | 持续显示对应日志 |

## Codex

在项目的本地环境动作菜单中选择「启动全部」「启动后端」「运行前端」「停止全部」
「查看状态」「后端日志」或「前端日志」。配置来自 `.codex/environments/environment.toml`。
动作通过 Git 动态定位当前项目根目录，不依赖某台电脑的绝对路径。

## 终端与运行行为

在项目根目录执行：

```bash
bash .codex/scripts/dev.sh start all
bash .codex/scripts/dev.sh status all
bash .codex/scripts/dev.sh logs backend
bash .codex/scripts/dev.sh stop all
```

`all` 也可替换为 `backend` 或 `frontend`。默认前端地址为 `http://127.0.0.1:5175`，
后端端口保持项目现有的 `5409`。入口采用 5175，减少与其他 Vite 项目常用 5173 的冲突；
原有 `npm run dev` 的默认端口不变。需要调整前端端口时，在执行入口前设置环境变量：

```bash
OMNIPOST_FRONTEND_PORT=5180 bash .codex/scripts/dev.sh start frontend
```

管理同一服务时需使用一致的端口设置；换端口前先用原端口执行停止命令。
脚本核对进程命令、工作目录和端口：本项目已运行就复用，其他程序占用端口则报错。
启动失败时查看对应日志；脚本只会清理本次启动失败的服务，已有服务保持原状。

服务在独立后台会话中运行。关闭启动任务的终端或结束日志查看不会停止服务，
使用「停止全部」明确停止。日志和 PID 位于已被 Git 忽略的 `logs/`，
停止服务不会删除账号会话、素材或数据库。多个启动管理命令同时执行时会提示稍后重试。

本次验证环境为 macOS；Linux / WSL 尚未实际运行验证。
