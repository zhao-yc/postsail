"""文章 API 的同步 CLI：不加载 Flask，也不直接操作账号 Cookie。"""

from __future__ import annotations

import argparse
import html
import json
import mimetypes
import os
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

import requests


from .platforms import ARTICLE_PLATFORMS
DEFAULT_SERVER = "http://127.0.0.1:5409"
STATUS_LABELS = {
    "scheduled": "等待排期",
    "cancelled": "已取消",
    "queued": "排队中",
    "running": "执行中",
    "needs_action": "需要处理",
    "previewed": "预览完成",
    "submitted": "平台已接收（可能仍在审核）",
    "published": "已发表",
    "failed": "失败",
    "unknown": "结果待确认",
}


class ArticleCliError(RuntimeError):
    """可直接给用户或智能体展示的 CLI 错误。"""


class ArticleApiClient:
    """只通过公开文章 API 上传素材和管理任务。"""

    def __init__(self, server: str, *, session=None, timeout: float = 30):
        parts = urlsplit(server)
        if parts.scheme not in ("http", "https") or not parts.hostname or parts.query or parts.fragment:
            raise ArticleCliError("服务地址必须是有效的 HTTP/HTTPS 地址，不能带查询参数或片段")
        self.server = server.rstrip("/")
        self.session = session or requests.Session()
        self.timeout = timeout

    def request(self, method: str, path: str, **kwargs) -> dict:
        """检查 HTTP 与业务码，保留完整 JSON envelope 供自动化消费。"""
        try:
            response = self.session.request(method, self.server + path,
                                            timeout=kwargs.pop("timeout", self.timeout), **kwargs)
        except requests.RequestException as exc:
            raise ArticleCliError(f"连接文章服务失败：{exc}") from exc
        try:
            result = response.json()
        except ValueError as exc:
            raise ArticleCliError(f"文章服务未返回 JSON（HTTP {response.status_code}）") from exc
        if not isinstance(result, dict) or "code" not in result:
            raise ArticleCliError("文章服务返回格式不正确，应包含 code、msg、data")
        if not 200 <= response.status_code < 300 or result["code"] != 200:
            raise ArticleCliError(str(result.get("msg") or f"请求失败（HTTP {response.status_code}）"))
        return result

    def upload_asset(self, source: str | Path) -> dict:
        """显式上传用户指定的本地文件；公开链接交由后端校验和导入。"""
        text = str(source)
        if urlsplit(text).scheme in ("http", "https"):
            return self.request("POST", "/api/article-assets", json={"url": text})["data"]
        path = Path(source).expanduser()
        if not path.is_file():
            raise ArticleCliError(f"图片文件不存在：{path}")
        with path.open("rb") as image_file:
            result = self.request(
                "POST", "/api/article-assets",
                files={"file": (path.name, image_file, mimetypes.guess_type(path.name)[0] or "application/octet-stream")},
            )
        return result["data"]


def _positive_id(value: str) -> int:
    """账号 ID 和修订号仍使用正整数。"""
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("ID 必须是正整数") from exc
    if number <= 0:
        raise argparse.ArgumentTypeError("ID 必须是正整数")
    return number


def _resource_id(value: str) -> str:
    """文章、素材、任务和批次使用不透明 ID，不能把 UUID 转为整数。"""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", value):
        raise argparse.ArgumentTypeError("资源 ID 只能包含字母、数字、下划线或短横线")
    return value


def _positive_seconds(value: str) -> float:
    """等待与网络超时必须有明确的正数上限。"""
    try:
        number = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("超时必须是正数秒数") from exc
    if not 0 < number < float("inf"):
        raise argparse.ArgumentTypeError("超时必须是有限的正数秒数")
    return number


def _add_connection_flags(parser, *, inherited=False):
    """参数可写在 article 前缀后，也可写在具体子命令后。"""
    missing = argparse.SUPPRESS if inherited else None
    parser.add_argument("--server", default=missing, help="服务地址；默认读取 OMNIPOST_API_URL")
    parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS if inherited else False,
                        help="输出 JSON；API 或执行失败也返回 JSON，退出码为 1")
    parser.add_argument("--request-timeout", type=_positive_seconds,
                        default=argparse.SUPPRESS if inherited else 30, help="单次 API 请求超时秒数（默认 30）")


def _add_article_fields(parser, *, creating=False):
    """导入与更新共用原稿字段；更新时未提供的字段保持原值。"""
    parser.add_argument("--file", type=Path, required=creating, help="UTF-8 正文文件，支持 Markdown、HTML、纯文本")
    parser.add_argument("--format", choices=("markdown", "html", "text"), help="正文格式，默认根据文件扩展名判断")
    parser.add_argument("--title", required=creating, help="文章标题")
    cover = parser.add_mutually_exclusive_group()
    cover.add_argument("--cover", help="封面本地路径或公开 HTTP/HTTPS 图片链接")
    cover.add_argument("--cover-asset-id", type=_resource_id, help="已上传的封面素材 ID")
    if not creating:
        cover.add_argument("--clear-cover", action="store_true", help="移除原稿封面")
    parser.add_argument("--tags", help="逗号分隔的话题；空字符串表示清空")
    parser.add_argument("--platform-options", type=Path, help="各平台默认覆盖项的 JSON 文件")


def _schedule_revision(value):
    """排期版本从 0 开始，不能沿用账号 ID 的正整数约束。"""
    try:
        revision = int(value)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("排期版本必须为非负整数") from exc
    if revision < 0:
        raise argparse.ArgumentTypeError("排期版本必须为非负整数")
    return revision


def add_article_parser(platform_parsers) -> None:
    """注册独立文章命令组，保持已有视频命令参数不变。"""
    parser = platform_parsers.add_parser("article", help="独立多平台文章管理与发布")
    _add_connection_flags(parser)
    actions = parser.add_subparsers(dest="action", required=True)

    create = actions.add_parser("import", help="导入原稿及本地正文图片")
    _add_article_fields(create, creating=True)
    update = actions.add_parser("update", help="修改原稿，校验修订号")
    update.add_argument("article_id", type=_resource_id)
    update.add_argument("--revision", type=_positive_id, help="预期修订号；默认先读取当前原稿")
    _add_article_fields(update)
    listing = actions.add_parser("list", help="列出已保存的文章")
    listing.add_argument("--limit", type=_positive_id, default=50)
    get = actions.add_parser("get", help="读取原稿和修订号")
    get.add_argument("article_id", type=_resource_id)
    accounts = actions.add_parser("accounts", help="列出支持文章发布的已有账号 ID")
    accounts.add_argument("--platform", dest="target_platform", choices=ARTICLE_PLATFORMS)
    actions.add_parser("capabilities", help="查询平台标题、封面与格式要求")
    asset = actions.add_parser("asset", help="单独上传图片，供封面覆盖项使用")
    source = asset.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", type=Path)
    source.add_argument("--url")

    publish = actions.add_parser("publish", help="创建发布批次，默认正式发布")
    publish.add_argument("article_id", type=_resource_id)
    publish.add_argument("--revision", type=_positive_id, help="发布指定修订；默认先读取当前修订")
    targets = publish.add_mutually_exclusive_group(required=True)
    targets.add_argument("--targets", type=Path, help="目标数组 JSON 文件，推荐用于多个平台")
    targets.add_argument("--account-id", type=_positive_id, action="append", help="同一平台账号 ID，可重复")
    publish.add_argument("--platform", dest="target_platform", choices=ARTICLE_PLATFORMS)
    publish.add_argument("--overrides", type=Path, help="--account-id 模式的公共覆盖项 JSON 文件")
    publish.add_argument("--preview", action="store_true", help="只准备并校验平台预览，不点击正式发布")
    publish.add_argument("--idempotency-key", help="重放同一次提交时复用此键；默认生成 UUID")
    publish.add_argument("--publish-at", help="文章/图文按所选时区开始提交的时间，例如 2026-10-06T10:00:00；由 PostSail 后端调度")
    publish.add_argument("--timezone", default="Asia/Shanghai", help="--publish-at 使用的 IANA 时区（默认 Asia/Shanghai）")

    pending = actions.add_parser("pending", help="分页列出所有原稿的待发布任务")
    pending.add_argument("--page", type=_positive_id, default=1)
    pending.add_argument("--page-size", type=_positive_id, default=50)
    reschedule = actions.add_parser("reschedule", help="修改尚未开始执行的文章/图文任务排期，保留原内容快照")
    reschedule.add_argument("task_id", type=_resource_id)
    reschedule.add_argument("--publish-at", required=True)
    reschedule.add_argument("--timezone", default="Asia/Shanghai")
    cancel = actions.add_parser("cancel", help="取消尚未开始执行的发布任务")
    cancel.add_argument("task_id", type=_resource_id)
    for command in (reschedule, cancel):
        command.add_argument("--schedule-revision", required=True, type=_schedule_revision,
                             help="pending/status 返回的 schedule_revision，防止覆盖其他入口的修改")

    status = actions.add_parser("status", help="查询批次及各账号状态")
    status.add_argument("batch_id", type=_resource_id)
    status.add_argument("--wait", action="store_true", help="每 2 秒查询，直到所有目标结束排期、排队和执行")
    status.add_argument("--timeout", type=_positive_seconds, default=300, help="--wait 截止秒数（默认 300）")
    retry = actions.add_parser("retry", help="安全重试一个失败或已处理的账号任务")
    retry.add_argument("task_id", type=_resource_id)
    resolve = actions.add_parser("resolve", help="核查未知结果，或凭文章链接将平台已受理任务确认为已发表",
                                 description="unknown 可记录核查结论；submitted 仅允许 published，须提供说明及 HTTP/HTTPS 文章链接，不会再次发布。")
    resolve.add_argument("task_id", type=_resource_id)
    resolve.add_argument("--resolution", required=True, choices=("not_published", "submitted", "published"))
    resolve.add_argument("--platform-url", help="核查得到的 HTTP/HTTPS 文章链接；确认 submitted 已发表时必填")
    resolve.add_argument("--note", required=True, help="人工核查依据；不会自动再次发布")
    for child in actions.choices.values():
        _add_connection_flags(child, inherited=True)


def _read_json(path: Path, expected_type: type) -> Any:
    """读取配置文件，输出中文错误并校验顶层类型。"""
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise ArticleCliError(f"读取 JSON 文件失败：{path}：{exc}") from exc
    if not isinstance(value, expected_type):
        raise ArticleCliError(f"JSON 文件顶层必须是{'数组' if expected_type is list else '对象'}：{path}")
    return value


def _markdown_prose_spans(content: str):
    """只扫描 Markdown 正文，跳过围栏代码、缩进代码和行内代码。"""
    offset = 0
    fence = None
    for line in content.splitlines(keepends=True):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
                fence = None
        elif marker:
            fence = marker[1]
        elif not line.startswith(("    ", "\t")):
            start = 0
            # 行内代码的反引号长度需匹配，代码示例中的图片不应被上传。
            for code in re.finditer(r"(?<!\\)(`+)(?!`)(.*?)\1(?!`)", line):
                if code.start() > start:
                    yield offset + start, line[start:code.start()]
                start = code.end()
            if start < len(line):
                yield offset + start, line[start:]
        offset += len(line)


def _markdown_image_urls(text: str):
    """提取行内图片地址位置，支持尖括号、转义字符和地址中的括号。"""
    cursor = 0
    while True:
        begin = text.find("![", cursor)
        if begin < 0:
            return
        cursor = begin + 2
        if begin and text[begin - 1] == "\\":
            continue
        depth = 1
        while cursor < len(text) and depth:
            if text[cursor] == "\\":
                cursor += 2
                continue
            depth += (text[cursor] == "[") - (text[cursor] == "]")
            cursor += 1
        if depth or cursor >= len(text) or text[cursor] != "(":
            continue
        cursor += 1
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1
        start = cursor
        if cursor < len(text) and text[cursor] == "<":
            end = text.find(">", cursor + 1)
            if end >= 0:
                yield cursor + 1, end, text[cursor + 1:end]
                cursor = end + 1
            continue
        depth = 0
        while cursor < len(text):
            char = text[cursor]
            if char == "\\":
                cursor += 2
                continue
            if char == ")" and depth == 0 or char.isspace():
                break
            depth += (char == "(") - (char == ")")
            cursor += 1
        if cursor > start:
            yield start, cursor, text[start:cursor]


def _html_image_urls(content: str):
    """只替换 img 的 src，不改变正文其他 HTML 标记或属性。"""
    for image in re.finditer(r"<img\b(?:[^>\"']|\"[^\"]*\"|'[^']*')*>?", content, re.I):
        attribute = re.search(r"(?<![\w:-])src\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))", image[0], re.I)
        if attribute:
            group = next(index for index in (1, 2, 3) if attribute[index] is not None)
            yield image.start() + attribute.start(group), image.start() + attribute.end(group), html.unescape(attribute[group])


def _local_image_path(raw_url: str, directory: Path) -> Path | None:
    """限制正文本地图片位于正文目录内，包含符号链接的最终真实路径校验。"""
    raw_url = re.sub(r"\\([ !\"#$%&'()*+,\-./:;<=>?@\[\]\\^_`{|}~])", r"\1", raw_url)
    parts = urlsplit(raw_url)
    if parts.scheme in ("http", "https") or raw_url.startswith("//"):
        return None
    if re.fullmatch(r"/api/article-assets/[A-Za-z0-9_-]{1,200}/content", parts.path):
        return None
    if parts.scheme or parts.netloc or not parts.path or parts.path.startswith(("/", "\\")):
        raise ArticleCliError(f"正文图片必须是目录内的相对路径或公开 HTTP/HTTPS 链接：{raw_url}")
    # Windows 路径也按目录分隔符处理，避免跨系统忽略反斜杠的目录穿越。
    relative = unquote(parts.path).replace("\\", "/")
    path = (directory / relative).resolve()
    try:
        path.relative_to(directory)
    except ValueError as exc:
        raise ArticleCliError(f"正文图片路径越出文章目录：{raw_url}") from exc
    if not path.is_file():
        raise ArticleCliError(f"正文图片不存在：{raw_url}")
    return path


def prepare_content(client: ArticleApiClient, file_path: Path, content_format: str | None) -> tuple[str, str]:
    """按原格式读取原稿，先验证全部本地路径，再上传并替换正文图片地址。"""
    path = file_path.expanduser().resolve()
    try:
        content = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise ArticleCliError(f"读取正文失败（需要 UTF-8 文件）：{path}：{exc}") from exc
    content_format = content_format or {".md": "markdown", ".markdown": "markdown", ".html": "html", ".htm": "html"}.get(path.suffix.lower(), "text")
    references = []
    if content_format == "html":
        references.extend(_html_image_urls(content))
    elif content_format == "markdown":
        prose = list(_markdown_prose_spans(content))
        used_refs = set()
        for offset, text in prose:
            references.extend((offset + start, offset + end, url) for start, end, url in _markdown_image_urls(text))
            references.extend((offset + start, offset + end, url) for start, end, url in _html_image_urls(text))
            for ref in re.finditer(r"(?<!\\)!\[((?:\\.|[^\]\\])*)\](?:\s*\[([^\]]*)\])?(?!\()", text):
                used_refs.add(" ".join((ref[2] or ref[1]).split()).casefold())
        for offset, text in prose:
            definition = re.match(r"^ {0,3}\[([^\]]+)\]:\s*(?:<([^>]+)>|([^\s]+))", text)
            if definition and " ".join(definition[1].split()).casefold() in used_refs:
                group = 2 if definition[2] is not None else 3
                references.append((offset + definition.start(group), offset + definition.end(group), definition[group]))
    resolved = [(start, end, _local_image_path(url, path.parent)) for start, end, url in references]
    uploaded = {}
    replacements = []
    for start, end, image_path in resolved:
        if image_path is None:
            continue
        if image_path not in uploaded:
            asset = client.upload_asset(image_path)
            if not isinstance(asset, dict) or not asset.get("url"):
                raise ArticleCliError("素材上传响应缺少 url")
            uploaded[image_path] = asset["url"]
        replacements.append((start, end, uploaded[image_path]))
    for start, end, url in sorted(set(replacements), reverse=True):
        content = content[:start] + url + content[end:]
    return content, content_format


def _article_payload(args, client: ArticleApiClient) -> dict:
    """只构造用户明确提供的字段，防止局部更新意外清空内容。"""
    payload = {}
    if args.title is not None:
        payload["title"] = args.title
    if args.file is not None:
        payload["content"], payload["format"] = prepare_content(client, args.file, args.format)
    elif args.format is not None:
        raise ArticleCliError("--format 需要同时提供 --file")
    if args.cover is not None:
        payload["cover_asset_id"] = client.upload_asset(args.cover)["id"]
    elif args.cover_asset_id is not None:
        payload["cover_asset_id"] = args.cover_asset_id
    elif getattr(args, "clear_cover", False):
        payload["cover_asset_id"] = None
    if args.tags is not None:
        payload["tags"] = [tag.strip().lstrip("#") for tag in args.tags.split(",") if tag.strip().lstrip("#")]
    if args.platform_options is not None:
        payload["platform_options"] = _read_json(args.platform_options, dict)
    return payload


def _publish_targets(args) -> list[dict]:
    """多平台以 JSON 文件为准，单平台可重复传账号 ID。"""
    if args.targets is not None:
        if args.target_platform or args.overrides:
            raise ArticleCliError("--targets 不能与 --platform 或 --overrides 同时使用")
        targets = _read_json(args.targets, list)
    else:
        if not args.target_platform:
            raise ArticleCliError("使用 --account-id 时必须提供 --platform")
        overrides = _read_json(args.overrides, dict) if args.overrides else {}
        targets = [{"platform": args.target_platform, "account_id": account_id, "overrides": overrides} for account_id in args.account_id]
    if not targets:
        raise ArticleCliError("至少需要一个发布目标")
    seen = set()
    for target in targets:
        if not isinstance(target, dict) or target.get("platform") not in ARTICLE_PLATFORMS:
            raise ArticleCliError("每个目标需指定支持的文章平台：" + "、".join(ARTICLE_PLATFORMS))
        if not isinstance(target.get("account_id"), int) or isinstance(target["account_id"], bool) or target["account_id"] <= 0:
            raise ArticleCliError("每个目标的 account_id 必须是正整数")
        if not isinstance(target.get("overrides", {}), dict):
            raise ArticleCliError("目标 overrides 必须是 JSON 对象")
        identity = (target["platform"], target["account_id"])
        if identity in seen:
            raise ArticleCliError("发布目标存在重复的平台与账号")
        seen.add(identity)
    return targets


def _is_batch_pending(data: Any) -> bool:
    """需要人工处理、审核中和结果待确认都结束等待，供调用者继续决策。"""
    if not isinstance(data, dict):
        return False
    tasks = data.get("tasks", [])
    if tasks:
        return any(task.get("status") in ("scheduled", "queued", "running") for task in tasks)
    return data.get("status") in ("scheduled", "queued", "running")


def _emit_result(result: dict, as_json: bool) -> None:
    """JSON 保留协议；可读模式把任务受理、审核与已发表分开显示。"""
    if as_json:
        print(json.dumps(result, ensure_ascii=False))
        return
    data = result.get("data")
    print(result.get("msg") or "操作完成")
    if result.get("idempotency_key"):
        print(f"幂等键：{result['idempotency_key']}")
    if isinstance(data, dict):
        if data.get("id") is not None:
            print(f"ID：{data['id']}")
        if data.get("revision") is not None:
            print(f"修订号：{data['revision']}")
        if data.get("status"):
            print(f"状态：{STATUS_LABELS.get(data['status'], data['status'])}")
        for task in data.get("tasks", data.get("items", [])):
            label = STATUS_LABELS.get(task.get("status"), task.get("status", "未知"))
            print(f"任务 {task.get('id', '?')}：{task.get('platform', '')} / 账号 {task.get('account_id', '?')}：{label}")
            if task.get("scheduled_at"):
                print(f"  排期（UTC）：{task['scheduled_at']}；时区：{task.get('schedule_timezone', '')}")
            if task.get("cancel_allowed"):
                print(f"  排期版本：{task.get('schedule_revision', 0)}")
            if task.get("message"):
                print(f"  详情：{task['message']}")
            if task.get("platform_status"):
                print(f"  平台状态：{task['platform_status']}")
            if task.get("platform_url"):
                print(f"  平台链接：{task['platform_url']}")
        if "items" in data:
            print(f"第 {data.get('page', 1)} 页，共 {data.get('total', 0)} 个待发布任务")
        if "tasks" in data or "items" in data:
            return
    print(json.dumps(data, ensure_ascii=False, indent=2))


def run_article_command(args) -> int:
    """执行一个文章命令；所有错误转换为确定的退出码和可机器读取输出。"""
    as_json = bool(args.json)
    operation_key = None
    try:
        client = ArticleApiClient(args.server or os.environ.get("OMNIPOST_API_URL") or DEFAULT_SERVER,
                                  timeout=args.request_timeout)
        if args.action == "import":
            result = client.request("POST", "/api/articles", json=_article_payload(args, client))
        elif args.action == "update":
            payload = _article_payload(args, client)
            if not payload:
                raise ArticleCliError("更新需提供标题、正文、封面、话题或平台配置中的至少一项")
            payload["expected_revision"] = args.revision or client.request("GET", f"/api/articles/{args.article_id}")["data"]["revision"]
            result = client.request("PATCH", f"/api/articles/{args.article_id}", json=payload)
        elif args.action == "list":
            result = client.request("GET", "/api/articles")
            if isinstance(result.get("data"), list):
                result = {**result, "data": result["data"][:args.limit]}
        elif args.action == "get":
            result = client.request("GET", f"/api/articles/{args.article_id}")
        elif args.action == "accounts":
            result = client.request("GET", "/api/article-accounts")
            if args.target_platform and isinstance(result.get("data"), list):
                result = {**result, "data": [account for account in result["data"] if account.get("platform") == args.target_platform]}
        elif args.action == "capabilities":
            result = client.request("GET", "/api/article-capabilities")
        elif args.action == "asset":
            result = {"code": 200, "msg": "素材已上传", "data": client.upload_asset(args.file or args.url)}
        elif args.action == "publish":
            targets = _publish_targets(args)
            if args.preview and (args.publish_at or any(target.get("schedule") is not None for target in targets)):
                raise ArticleCliError("平台预览不能排期，请移除发布时间后立即预览")
            revision = args.revision or client.request("GET", f"/api/articles/{args.article_id}")["data"]["revision"]
            payload = {"revision": revision, "targets": targets, "mode": "preview" if args.preview else "publish",
                       "idempotency_key": args.idempotency_key or str(uuid.uuid4())}
            operation_key = payload["idempotency_key"]
            if args.publish_at:
                payload["schedule"] = {"publish_at": args.publish_at, "timezone": args.timezone}
            result = client.request("POST", f"/api/articles/{args.article_id}/publish", json=payload)
            # 输出保存实际使用的幂等键；连接失败时请先查询现有记录，不能盲目重放。
            result = {**result, "idempotency_key": payload["idempotency_key"]}
        elif args.action == "pending":
            result = client.request("GET", "/api/article-publish-tasks", params={"page": args.page, "page_size": args.page_size})
        elif args.action in {"reschedule", "cancel"}:
            payload = {"expected_schedule_revision": args.schedule_revision}
            if args.action == "reschedule":
                payload["schedule"] = {"publish_at": args.publish_at, "timezone": args.timezone}
                result = client.request("PATCH", f"/api/article-publish-tasks/{args.task_id}/schedule", json=payload)
            else:
                result = client.request("POST", f"/api/article-publish-tasks/{args.task_id}/cancel", json=payload)
        elif args.action == "status":
            deadline = time.monotonic() + args.timeout
            result = client.request("GET", f"/api/article-publish-batches/{args.batch_id}", timeout=min(client.timeout, args.timeout))
            while args.wait and _is_batch_pending(result.get("data")):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    _emit_result({**result, "msg": "等待超时；任务继续执行，可再次查询", "wait_timed_out": True}, as_json)
                    return 2
                time.sleep(min(2, remaining))
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    _emit_result({**result, "msg": "等待超时；任务继续执行，可再次查询", "wait_timed_out": True}, as_json)
                    return 2
                result = client.request("GET", f"/api/article-publish-batches/{args.batch_id}", timeout=min(client.timeout, remaining))
        elif args.action == "retry":
            result = client.request("POST", f"/api/article-publish-tasks/{args.task_id}/retry", json={})
        elif args.action == "resolve":
            payload = {"resolution": args.resolution, "note": args.note}
            if args.platform_url:
                payload["platform_url"] = args.platform_url
            result = client.request("POST", f"/api/article-publish-tasks/{args.task_id}/resolve", json=payload)
        else:
            raise ArticleCliError(f"未知文章命令：{args.action}")
        _emit_result(result, as_json)
        return 0
    except (ArticleCliError, KeyError, TypeError, ValueError, OSError) as exc:
        error = {"code": 1, "msg": str(exc), "data": None}
        if operation_key:
            error["idempotency_key"] = operation_key
        if as_json:
            print(json.dumps(error, ensure_ascii=False))
        else:
            print(f"文章命令失败：{exc}", file=sys.stderr)
            if operation_key:
                print(f"幂等键：{operation_key}；请复用此键核查提交，不能换新键盲目重发", file=sys.stderr)
        return 1
