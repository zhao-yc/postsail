# uploader/bilibili_uploader/content_stats.py
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from utils.log import bilibili_logger

ARCHIVES_URL = "https://member.bilibili.com/x/web/archives"
DEFAULT_STATUS = "pubed,is_pubing,not_pubed"
REQUEST_TIMEOUT = 30


class BilibiliStatsSyncError(Exception):
    def __init__(self, message: str, code: int = 500):
        super().__init__(message)
        self.code = code
        self.message = message


def normalize_count(value: Any) -> int:
    if value is None or value == "":
        return 0
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def load_bilibili_cookies(account_file: str | Path) -> dict[str, str]:
    path = Path(account_file)
    if not path.exists():
        raise BilibiliStatsSyncError("cookie 文件不存在，请先在账号管理中登录 B 站", code=401)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BilibiliStatsSyncError(f"cookie 文件无法解析: {exc}", code=401) from exc

    raw_cookies = None
    if isinstance(payload, dict):
        cookie_info = payload.get("cookie_info")
        if isinstance(cookie_info, dict):
            raw_cookies = cookie_info.get("cookies")
        if raw_cookies is None:
            raw_cookies = payload.get("cookies")
    if not isinstance(raw_cookies, list) or not raw_cookies:
        raise BilibiliStatsSyncError("cookie 格式无效（需要 biliup cookie_info）", code=401)

    cookies: dict[str, str] = {}
    for item in raw_cookies:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        value = item.get("value")
        if name and value is not None:
            cookies[str(name)] = str(value)
    if "SESSDATA" not in cookies:
        raise BilibiliStatsSyncError("cookie 缺少 SESSDATA，请重新登录 B 站", code=401)
    return cookies


def _extract_list(payload: dict) -> list:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, dict):
        for key in ("arc_audits", "archives"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    for key in ("arc_audits", "archives"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


def _archive_block(raw: dict) -> dict:
    if not isinstance(raw, dict):
        return {}
    for key in ("Archive", "archive"):
        block = raw.get(key)
        if isinstance(block, dict):
            return block
    return raw


def _stat_block(raw: dict) -> dict:
    if not isinstance(raw, dict):
        return {}
    for key in ("stat", "Stat"):
        block = raw.get(key)
        if isinstance(block, dict):
            return block
    return {}


def _item_sort_ts(raw: dict) -> int:
    archive = _archive_block(raw)
    ts = archive.get("ptime") or archive.get("ctime") or archive.get("dtime") or 0
    try:
        ts_i = int(ts)
    except (TypeError, ValueError):
        return 0
    if ts_i > 10_000_000_000:
        ts_i //= 1000
    return ts_i


def _published_at(raw: dict) -> str:
    ts = _item_sort_ts(raw)
    if not ts:
        return ""
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError):
        return ""


def normalize_cover_url(url: Any) -> str:
    text = str(url or "").strip()
    if text.startswith("http://"):
        # hdslb CDN works over https; avoid mixed-content / fragile http links
        text = "https://" + text[len("http://") :]
    return text


def parse_bilibili_item(raw: dict) -> dict | None:
    if not isinstance(raw, dict):
        return None
    archive = _archive_block(raw)
    stat = _stat_block(raw)
    item_id = archive.get("bvid") or archive.get("aid") or raw.get("bvid") or raw.get("aid")
    if item_id is None or str(item_id).strip() == "":
        return None
    return {
        "item_id": str(item_id),
        "title": str(archive.get("title") or "").strip(),
        "cover_url": normalize_cover_url(archive.get("cover")),
        "status": str(archive.get("state_desc") or "").strip() or "已发布",
        "published_at": _published_at(raw),
        "play_count": normalize_count(stat.get("view", stat.get("vv", 0))),
        "like_count": normalize_count(stat.get("like", 0)),
        "comment_count": normalize_count(stat.get("reply", 0)),
        "share_count": normalize_count(stat.get("share", 0)),
        "collect_count": normalize_count(stat.get("favorite", 0)),
        "raw_json": json.dumps(raw, ensure_ascii=False)[:8000],
    }


def parse_bilibili_list_payload(payload: dict, limit: int = 5) -> list[dict]:
    limit = max(0, int(limit))
    raw_items = [raw for raw in _extract_list(payload) if isinstance(raw, dict)]
    raw_items.sort(key=_item_sort_ts, reverse=True)
    items: list[dict] = []
    for raw in raw_items:
        parsed = parse_bilibili_item(raw)
        if parsed:
            items.append(parsed)
        if len(items) >= limit:
            break
    return items


def fetch_archives_payload(cookies: dict[str, str], page_size: int = 20) -> dict:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Referer": "https://member.bilibili.com/platform/upload-manager/article",
        "Origin": "https://member.bilibili.com",
    }
    params = {
        "status": DEFAULT_STATUS,
        "pn": 1,
        "ps": max(1, min(int(page_size), 50)),
        "coop": 1,
        "interactive": 1,
    }
    try:
        response = requests.get(
            ARCHIVES_URL,
            params=params,
            cookies=cookies,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise BilibiliStatsSyncError(f"请求 B 站稿件列表失败: {exc}", code=500) from exc

    if response.status_code in (401, 403):
        raise BilibiliStatsSyncError("B 站 cookie 已失效，请重新登录", code=401)
    if response.status_code != 200:
        raise BilibiliStatsSyncError(f"B 站稿件列表 HTTP {response.status_code}", code=500)

    try:
        payload = response.json()
    except ValueError as exc:
        raise BilibiliStatsSyncError("B 站稿件列表返回非 JSON", code=500) from exc

    if not isinstance(payload, dict):
        raise BilibiliStatsSyncError("B 站稿件列表格式异常", code=500)

    code = payload.get("code")
    if code not in (0, "0", None):
        message = str(payload.get("message") or payload.get("msg") or code)
        if code in (-101, -111, 401) or "登录" in message:
            raise BilibiliStatsSyncError(f"B 站 cookie 已失效: {message}", code=401)
        raise BilibiliStatsSyncError(f"B 站稿件列表返回异常: {message}", code=500)
    return payload


def sync_recent_items(account_file: str | Path, limit: int = 5) -> list[dict]:
    cookies = load_bilibili_cookies(account_file)
    page_size = max(int(limit), 10)
    payload = fetch_archives_payload(cookies, page_size=page_size)
    items = parse_bilibili_list_payload(payload, limit=limit)
    bilibili_logger.info(f"B站稿件同步完成: {len(items)} 条 (limit={limit})")
    return items


def sync_recent_items_sync(account_file: str | Path, limit: int = 5, headless: bool | None = None) -> list[dict]:
    # headless kept for API symmetry with other platforms; unused (HTTP sync).
    _ = headless
    return sync_recent_items(account_file, limit=limit)
