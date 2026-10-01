"""管理本地 Web 服务；VS Code、Codex 与终端共用此入口。"""

import argparse
import fcntl
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
from urllib.request import ProxyHandler, build_opener


ROOT = Path(__file__).resolve().parents[2]
LOGS = ROOT / "logs"
HTTP = build_opener(ProxyHandler({}))


def process_matches(pid, service):
    """同时核对进程命令和工作目录，避免误用旧 PID 或停止其他项目。"""
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True
    )
    if result.returncode == 1 and not result.stderr:
        return False
    if result.returncode:
        raise RuntimeError(f"无法读取进程 {pid}：{result.stderr.strip()}")
    command = result.stdout.strip()
    cwd = subprocess.run(
        ["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
        capture_output=True, text=True,
    )
    expected = ROOT if service == "backend" else ROOT / "sau_frontend"
    directories = [line[1:] for line in cwd.stdout.splitlines() if line.startswith("n")]
    same_directory = any(Path(directory).resolve() == expected for directory in directories)
    marker = "sau_backend.py" in command if service == "backend" else (
        "npm run dev" in command or "/vite" in command
    )
    return same_directory and marker


def listener_pids(port):
    """查明端口的监听进程；不把其他程序占用的端口当成启动成功。"""
    result = subprocess.run(
        ["lsof", "-nP", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"],
        capture_output=True, text=True,
    )
    if result.returncode not in (0, 1) or result.stderr:
        raise RuntimeError(f"无法检查端口 {port}：{result.stderr.strip()}")
    return {int(line) for line in result.stdout.splitlines() if line.strip()}


def owned_listeners(service, port):
    """端口冲突时直接报错，要求使用者先核对占用来源。"""
    pids = listener_pids(port)
    for pid in pids:
        if not process_matches(pid, service):
            raise RuntimeError(f"端口 {port} 被其他进程占用（PID {pid}），未启动或停止该进程。")
    return pids


def saved_pid(service):
    """PID 文件仅是线索，使用前仍须检查真实进程归属。"""
    try:
        return int((LOGS / f"{service}.pid").read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def healthy(service, port):
    """通过真实 HTTP 响应确认就绪，后端要求账号接口返回正常状态。"""
    path = "/getAccounts" if service == "backend" else "/"
    try:
        with HTTP.open(f"http://127.0.0.1:{port}{path}", timeout=1) as response:
            body = response.read().decode("utf-8")
            return json.loads(body).get("code") == 200 if service == "backend" else "/@vite/client" in body
    except (OSError, ValueError):
        return False


def signal_process(pid, service, sig):
    """只对已核实的项目进程发信号；独立进程组同时清理 npm 的 Vite 子进程。"""
    if not process_matches(pid, service):
        return
    try:
        if os.getpgid(pid) == pid:
            os.killpg(pid, sig)
        else:
            os.kill(pid, sig)
    except ProcessLookupError:
        pass


def stop(service, port):
    """先温和退出，必要时清理仍占用端口的已确认项目进程。"""
    pids = owned_listeners(service, port)
    pid = saved_pid(service)
    if pid and process_matches(pid, service):
        pids.add(pid)
    for pid in pids:
        signal_process(pid, service, signal.SIGTERM)
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        remaining = {pid for pid in pids if process_matches(pid, service)}
        remaining.update(owned_listeners(service, port))
        if not remaining:
            break
        time.sleep(0.2)
    else:
        for pid in remaining:
            signal_process(pid, service, signal.SIGKILL)
        time.sleep(0.5)
    if owned_listeners(service, port) or any(process_matches(pid, service) for pid in pids):
        raise RuntimeError(f"{service} 尚未完全停止，请查看日志和进程状态。")
    (LOGS / f"{service}.pid").unlink(missing_ok=True)
    print(f"已停止 {service}。" if pids else f"{service} 当前未运行。")


def start(service, port):
    """复用健康服务，或脱离编辑器终端启动并等待 HTTP 就绪。"""
    pids = owned_listeners(service, port)
    pid = saved_pid(service)
    running = pid is not None and process_matches(pid, service)
    process = None
    if not pids and not running:
        if service == "backend":
            for relative in ("conf.py", "db/database.db"):
                if not (ROOT / relative).is_file():
                    raise RuntimeError(f"缺少 {relative}，请先按 docs/install.md 完成配置和数据库初始化。")
            command = [sys.executable, "-u", "sau_backend.py"]
            cwd = ROOT
        else:
            cwd = ROOT / "sau_frontend"
            if not (cwd / "node_modules/vite/bin/vite.js").is_file():
                raise RuntimeError("缺少前端依赖，请先在 sau_frontend 中执行 npm install。")
            npm = shutil.which("npm")
            if not npm:
                raise RuntimeError("未找到 npm，请安装 Node.js 18+。")
            command = [npm, "run", "dev", "--", "--host", "127.0.0.1", "--port", str(port), "--strictPort"]
        with (LOGS / f"{service}.log").open("ab") as log:
            # 独立会话保证关闭任务终端后服务继续运行，输出始终落入日志文件。
            process = subprocess.Popen(
                command, cwd=cwd, stdin=subprocess.DEVNULL, stdout=log,
                stderr=subprocess.STDOUT, start_new_session=True,
            )
        (LOGS / f"{service}.pid").write_text(f"{process.pid}\n")
    elif not running and pids:
        (LOGS / f"{service}.pid").write_text(f"{min(pids)}\n")
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if owned_listeners(service, port) and healthy(service, port):
            verb = "已启动" if process else "已复用"
            print(f"{verb} {service}：http://127.0.0.1:{port}")
            return
        if process and process.poll() is not None:
            break
        time.sleep(0.3)
    if process:
        stop(service, port)
    raise RuntimeError(f"{service} 未就绪，请查看 logs/{service}.log 或运行日志任务。")


def main():
    """统一参数、运行锁与错误提示，使所有编辑器入口行为一致。"""
    parser = argparse.ArgumentParser(description="PostSail 播舟 本地启动、停止、状态和日志")
    parser.add_argument("action", choices=("start", "stop", "status", "logs"))
    parser.add_argument("service", nargs="?", default="all", choices=("all", "backend", "frontend"))
    args = parser.parse_args()
    port = int(os.environ.get("OMNIPOST_FRONTEND_PORT", "5175"))
    if not 1 <= port <= 65535 or port == 5409:
        raise RuntimeError("OMNIPOST_FRONTEND_PORT 必须是 1～65535 内且不同于后端 5409 的端口。")
    services = {"backend": 5409, "frontend": port}
    if args.service != "all":
        services = {args.service: services[args.service]}
    LOGS.mkdir(exist_ok=True)
    if args.action == "logs":
        paths = [LOGS / f"{service}.log" for service in services]
        for path in paths:
            path.touch(exist_ok=True)
        print("正在查看日志，按 Ctrl+C 结束查看，服务会继续运行。", flush=True)
        return subprocess.call(["tail", "-n", "40", "-F", *map(str, paths)])
    for tool in ("ps", "lsof"):
        if not shutil.which(tool):
            raise RuntimeError(f"缺少 {tool}，请先安装系统工具；Windows 请使用 WSL。")
    with (LOGS / ".dev.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("另一条启动管理命令正在执行，请稍后重试。") from None
        if args.action == "start":
            # 启动全部前先检查两个端口，避免已知冲突导致只启动一半。
            for service, service_port in services.items():
                owned_listeners(service, service_port)
        entries = list(services.items())
        if args.action == "stop":
            entries.reverse()
        for service, service_port in entries:
            if args.action == "status":
                pids = owned_listeners(service, service_port)
                ready = bool(pids) and healthy(service, service_port)
                state = "运行正常" if ready else "尚未就绪" if pids else "未运行"
                print(f"{service}：{state}，端口 {service_port}，监听 PID {sorted(pids)}")
            elif args.action == "start":
                start(service, service_port)
            else:
                stop(service, service_port)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, ValueError, OSError) as error:
        print(f"操作失败：{error}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
