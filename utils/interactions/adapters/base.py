"""互动适配器的公共契约、凭据读取与安全请求。"""
from __future__ import annotations

import base64
import json
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests


class InteractionAdapterError(Exception):
    """可直接传给界面的中文错误；未知发送结果必须禁止重试。"""

    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.code, self.message, self.retryable = code, message, retryable


def account_value(account: Any, key: str, default=None):
    """兼容服务层字典和类型化账号对象。"""
    return account.get(key, default) if isinstance(account, dict) else getattr(account, key, default)


def read_state(account: Any) -> dict:
    """只在调用时读取账号凭据，不在日志或异常中输出文件内容。"""
    path = account_value(account, "cookie_path")
    if not path:
        raise InteractionAdapterError("needs_login", "请先在账号管理中登录该平台")
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError) as exc:
        raise InteractionAdapterError("needs_login", "账号登录文件缺失或无法解析，请重新登录") from exc
    if not isinstance(payload, dict):
        raise InteractionAdapterError("needs_login", "账号登录文件格式错误，请重新登录")
    return payload


def load_cookies(account: Any, host: str, required=()) -> dict[str, str]:
    """仅向平台自身域名转交 cookie，兼容 biliup 和 Playwright 文件。"""
    state = read_state(account)
    rows = state.get("cookies") or state.get("cookie_info", {}).get("cookies") or []
    cookies = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        domain = str(row.get("domain") or "").lstrip(".")
        if domain and host != domain and not host.endswith("." + domain):
            continue
        if row.get("name") and row.get("value") is not None:
            cookies[str(row["name"])] = str(row["value"])
    if not cookies or any(not cookies.get(key) for key in required):
        raise InteractionAdapterError("needs_login", "该平台的登录凭据不完整，请重新登录")
    return cookies


def timestamp(value: Any) -> str:
    """统一输出带 UTC 时区的时间，保持跨机器一致。"""
    if isinstance(value, str) and not value.isdigit():
        return value
    try:
        number = float(value or 0)
        while number > 10_000_000_000:
            number /= 1000
        return datetime.fromtimestamp(number, tz=timezone.utc).isoformat() if number else ""
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def encode_cursor(value: dict) -> str:
    """游标只携带翻页状态，不携带登录凭据。"""
    return base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode()).decode()


def decode_cursor(value: str | None) -> dict:
    """拒绝过大的、不完整的游标，避免默默重复第一页。"""
    if value is None or value == "":
        return {}
    try:
        if len(value) > 4096:
            raise ValueError()
        result = json.loads(base64.urlsafe_b64decode(value.encode()))
        if not isinstance(result, dict):
            raise ValueError()
        return result
    except (ValueError, TypeError, UnicodeError) as exc:
        raise InteractionAdapterError("invalid_cursor", "分页游标无效，请重新同步") from exc


def validate_reply(message: dict, text: str, reply_key: str) -> str:
    """发送必须有明确目标、非空内容和持久化幂等键。"""
    content = str(text or "").strip()
    if not content or len(content) > 1000:
        raise InteractionAdapterError("invalid_reply", "回复内容应为 1 至 1000 个字符")
    if not str(reply_key or "").strip():
        raise InteractionAdapterError("invalid_reply", "回复缺少幂等标识")
    if not message.get("platformMessageId") or message.get("kind") not in {"comment", "private", "welcome"}:
        raise InteractionAdapterError("invalid_target", "回复目标缺少平台消息标识")
    return content


def business_code(value, platform: str, sending=False) -> int:
    """业务码必须是明确整数；缺字段、布尔值和未知格式不能确认发送失败。"""
    if isinstance(value, bool) or not isinstance(value, (int, str)) or not re.fullmatch(r"-?\d+", str(value)):
        raise InteractionAdapterError("send_unknown" if sending else "invalid_response", f"{platform}缺少明确的业务回执，请核对平台结果")
    return int(value)


def request_json(method: str, url: str, *, sending: bool = False, **kwargs) -> dict:
    """固定超时、验证 TLS、不跟随重定向；发送超时不能当成失败重发。"""
    try:
        response = requests.request(method, url, timeout=30, allow_redirects=False, **kwargs)
    except requests.RequestException as exc:
        code = "send_unknown" if sending else "network_error"
        message = "发送结果待确认，请先到平台核对，不能自动重试" if sending else "平台连接失败，请检查网络后重试"
        raise InteractionAdapterError(code, message, retryable=not sending) from exc
    if response.status_code in (401, 403):
        raise InteractionAdapterError("needs_login", "平台拒绝当前登录态，请重新登录或完成验证")
    if not 200 <= response.status_code < 300:
        raise InteractionAdapterError("send_unknown" if sending else "platform_error", "平台请求未成功，请核对平台状态", retryable=not sending)
    try:
        payload = response.json()
    except ValueError as exc:
        raise InteractionAdapterError("send_unknown" if sending else "invalid_response", "平台响应格式异常，发送操作请先到平台核对") from exc
    if not isinstance(payload, dict):
        raise InteractionAdapterError("send_unknown" if sending else "invalid_response", "平台响应不是有效的数据对象")
    return payload


def require_kind(kind: str, supported: tuple[str, ...]):
    """未实现的类型明确拒绝，不返回空列表伪装成功。"""
    if kind not in supported:
        raise InteractionAdapterError("unsupported", "该平台暂未接入此类互动，请使用平台官方客户端")


@contextmanager
def browser_page(account: Any, start_url: str):
    """沿用项目可配置的系统浏览器和账号存储，不硬编码个人机器路径。"""
    from patchright.sync_api import sync_playwright
    from conf import LOCAL_CHROME_HEADLESS, LOCAL_CHROME_PATH
    from utils.browser_options import get_browser_options

    state = read_state(account)
    if not isinstance(state.get("cookies"), list):
        raise InteractionAdapterError("needs_login", "网页互动需要 Playwright 格式的登录态，请重新登录")
    with sync_playwright() as runtime:
        try:
            browser = runtime.chromium.launch(**get_browser_options(LOCAL_CHROME_HEADLESS, LOCAL_CHROME_PATH))
        except Exception as exc:
            raise InteractionAdapterError("browser_unavailable", "无法启动浏览器，请配置 Chrome 路径或安装系统 Chrome") from exc
        try:
            context = browser.new_context(storage_state={"cookies": state["cookies"], "origins": state.get("origins", [])})
            page = context.new_page()
            page.goto(start_url, wait_until="domcontentloaded", timeout=30000)
            if any(word in urlsplit(page.url).path for word in ("login", "passport")):
                raise InteractionAdapterError("needs_login", "网页登录态已失效，请重新登录")
            yield page
        finally:
            browser.close()
