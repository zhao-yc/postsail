"""文章会话读取与校验；B站视频凭据只在内存转换，保留原始 biliup 文件。"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path


def normalize_article_storage_state(platform: str, payload: dict) -> dict:
    """返回可直接交给 Playwright 的 state，拒绝无效 Cookie 和本地存储结构。"""
    if not isinstance(payload, dict):
        raise ValueError("Cookie 文件必须为 JSON 对象")
    state = copy.deepcopy(payload)
    if platform == "bilibili" and isinstance(state.get("cookie_info"), dict):
        # biliup 缺少浏览器属性；补上标准属性而不改变视频上传器使用的文件。
        cookies = state["cookie_info"].get("cookies")
        if not isinstance(cookies, list):
            raise ValueError("B站 biliup 文件缺少 cookie_info.cookies")
        state = {"cookies": cookies, "origins": []}
        for cookie in cookies:
            if not isinstance(cookie, dict):
                raise ValueError("Cookie 条目必须为对象")
            cookie.setdefault("domain", ".bilibili.com")
            cookie.setdefault("path", "/")
            cookie.setdefault("expires", -1)
            cookie.setdefault("httpOnly", False)
            cookie.setdefault("secure", True)
            cookie.setdefault("sameSite", "Lax")
    if not isinstance(state.get("cookies"), list) or not isinstance(state.get("origins"), list):
        raise ValueError("请导入 Playwright storage_state（cookies 和 origins）或 B站 biliup JSON")
    allowed_cookie_fields = {"name", "value", "domain", "path", "expires", "httpOnly", "secure", "sameSite", "partitionKey"}
    clean_cookies = []
    for cookie in state["cookies"]:
        if not isinstance(cookie, dict) or any(not isinstance(cookie.get(key), str) for key in ("name", "value", "domain", "path")):
            raise ValueError("Cookie 必须包含文本 name、value、domain 和 path")
        if not cookie["name"] or not cookie["domain"] or not cookie["path"].startswith("/"):
            raise ValueError("Cookie 名称、域名或路径无效")
        for key, default in (("expires", -1), ("httpOnly", False), ("secure", False), ("sameSite", "Lax")):
            cookie.setdefault(key, default)
        if (isinstance(cookie["expires"], bool) or not isinstance(cookie["expires"], (int, float))
                or not math.isfinite(cookie["expires"])):
            raise ValueError("Cookie 过期时间必须为有效数字")
        if not isinstance(cookie["httpOnly"], bool) or not isinstance(cookie["secure"], bool) or cookie["sameSite"] not in {"Strict", "Lax", "None"}:
            raise ValueError("Cookie 浏览器属性无效")
        clean_cookies.append({key: value for key, value in cookie.items() if key in allowed_cookie_fields})
    for origin in state["origins"]:
        if not isinstance(origin, dict) or not isinstance(origin.get("origin"), str) or not isinstance(origin.get("localStorage"), list):
            raise ValueError("origins 必须包含 origin 和 localStorage")
        for item in origin["localStorage"]:
            if not isinstance(item, dict) or any(not isinstance(item.get(key), str) for key in ("name", "value")):
                raise ValueError("localStorage 条目必须包含文本 name 和 value")
    return {"cookies": clean_cookies, "origins": state["origins"]}


def load_article_storage_state(platform: str, account_file: str | Path) -> dict:
    """读取标准会话或 biliup Cookie；本函数绝不写入账号文件。"""
    try:
        payload = json.loads(Path(account_file).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise ValueError("账号 Cookie 文件不存在或不是有效 JSON") from exc
    return normalize_article_storage_state(platform, payload)
