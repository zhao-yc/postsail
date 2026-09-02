# uploader/xiaohongshu_uploader/content_stats.py
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from patchright.async_api import async_playwright

from conf import LOCAL_CHROME_HEADLESS, LOCAL_CHROME_PATH
from utils.base_social_media import set_init_script
from utils.log import xiaohongshu_logger

MANAGE_URL = "https://creator.xiaohongshu.com/new/note-manager"

XHS_LIST_URL_HINTS = (
    "api/galaxy/v2/creator/note/user/posted",
    "creator/note/user/posted",
    "note/user/posted",
)


class XiaohongshuStatsSyncError(Exception):
    def __init__(self, message: str, code: int = 500):
        super().__init__(message)
        self.code = code
        self.message = message


def is_xiaohongshu_list_api_url(url: str) -> bool:
    u = (url or "").lower()
    return any(hint in u for hint in XHS_LIST_URL_HINTS)


def normalize_count(value: Any) -> int:
    if value is None or value == "":
        return 0
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _extract_list(payload: dict) -> list:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, dict):
        for key in ("notes", "note_list", "list"):
            value = data.get(key)
            if isinstance(value, list):
                return value
        return _extract_list(data)
    for key in ("notes", "note_list", "list"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


def merge_intercepted_payloads(payloads: list[dict]) -> dict:
    best: dict = {}
    best_len = -1
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        length = len(_extract_list(payload))
        if length > best_len:
            best = payload
            best_len = length
    return best


def _item_sort_ts(raw: dict) -> int:
    ts = raw.get("visible_time") or raw.get("time") or raw.get("create_time") or raw.get("schedule_post_time") or 0
    try:
        ts_i = int(ts)
        if ts_i > 10_000_000_000:
            ts_i //= 1000
        return ts_i
    except (TypeError, ValueError):
        return 0


def _published_at(raw: dict) -> str:
    ts = _item_sort_ts(raw)
    if not ts:
        return ""
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError):
        return str(raw.get("visible_time") or "")


def _cover_url(raw: dict) -> str:
    imgs = raw.get("images_list") or raw.get("images") or []
    if isinstance(imgs, list) and imgs:
        first = imgs[0]
        if isinstance(first, dict):
            return str(first.get("url") or first.get("url_size_large") or "")
        if isinstance(first, str):
            return first
    video = raw.get("video_info") or {}
    if isinstance(video, dict):
        return str(video.get("cover") or video.get("thumbnail") or "")
    return str(raw.get("cover") or raw.get("cover_url") or "")


def _status_text(raw: dict) -> str:
    msg = raw.get("permission_msg")
    if isinstance(msg, str) and msg.strip():
        return msg.strip()
    if raw.get("sticky"):
        return "已发布(置顶)"
    tab = raw.get("tab_status")
    mapping = {
        0: "已发布",
        1: "定时发布",
        2: "草稿",
        3: "已删除",
    }
    if tab in mapping:
        return mapping[tab]
    return "已发布"


def parse_xiaohongshu_item(raw: dict) -> dict | None:
    if not isinstance(raw, dict):
        return None
    item_id = raw.get("id") or raw.get("note_id") or raw.get("noteId")
    if item_id is None or str(item_id).strip() == "":
        return None
    return {
        "item_id": str(item_id),
        "title": str(raw.get("display_title") or raw.get("title") or raw.get("desc") or "").strip(),
        "cover_url": _cover_url(raw),
        "status": _status_text(raw),
        "published_at": _published_at(raw),
        "play_count": normalize_count(raw.get("view_count", raw.get("read_count", 0))),
        "like_count": normalize_count(raw.get("likes", raw.get("liked_count", raw.get("like_count", 0)))),
        "comment_count": normalize_count(raw.get("comments_count", raw.get("comment_count", 0))),
        "share_count": normalize_count(raw.get("shared_count", raw.get("share_count", 0))),
        "collect_count": normalize_count(raw.get("collected_count", raw.get("collect_count", 0))),
        "raw_json": json.dumps(raw, ensure_ascii=False)[:8000],
    }


def parse_xiaohongshu_list_payload(payload: dict, limit: int = 5) -> list[dict]:
    limit = max(0, int(limit))
    raw_items = [raw for raw in _extract_list(payload) if isinstance(raw, dict)]
    raw_items.sort(key=_item_sort_ts, reverse=True)
    items: list[dict] = []
    for raw in raw_items:
        parsed = parse_xiaohongshu_item(raw)
        if parsed:
            items.append(parsed)
        if len(items) >= limit:
            break
    return items


async def sync_recent_items(account_file: str | Path, limit: int = 5, headless: bool | None = None) -> list[dict]:
    account_file = Path(account_file)
    if not account_file.exists():
        raise XiaohongshuStatsSyncError("cookie 文件不存在，请先在账号管理中登录小红书", code=401)

    headless = LOCAL_CHROME_HEADLESS if headless is None else headless
    payloads: list[dict] = []

    async with async_playwright() as playwright:
        launch_args = {"headless": headless}
        if LOCAL_CHROME_PATH:
            launch_args["executable_path"] = LOCAL_CHROME_PATH
        else:
            launch_args["channel"] = "chrome"
        browser = await playwright.chromium.launch(**launch_args)
        try:
            context = await browser.new_context(storage_state=str(account_file))
            context = await set_init_script(context)
            page = await context.new_page()

            async def on_response(response):
                try:
                    if not is_xiaohongshu_list_api_url(response.url):
                        return
                    if response.status != 200:
                        return
                    data = await response.json()
                    if isinstance(data, dict):
                        payloads.append(data)
                except Exception as exc:
                    xiaohongshu_logger.debug("intercept response parse failed: %s", exc)
                    return

            page.on("response", on_response)
            await page.goto(MANAGE_URL, wait_until="domcontentloaded", timeout=60000)

            for _ in range(40):
                if await page.get_by_text("扫码登录").count() or await page.get_by_text("手机号登录").count():
                    raise XiaohongshuStatsSyncError("小红书 cookie 已失效，请重新登录", code=401)
                if any(_extract_list(p) for p in payloads):
                    break
                # success empty list also ok once API returned
                if any(
                    isinstance(p, dict) and p.get("success") is True and isinstance((p.get("data") or {}), dict)
                    for p in payloads
                ):
                    break
                await page.wait_for_timeout(500)
            else:
                await page.reload(wait_until="domcontentloaded", timeout=60000)
                for _ in range(20):
                    if any(_extract_list(p) for p in payloads) or any(
                        isinstance(p, dict) and p.get("success") is True for p in payloads
                    ):
                        break
                    await page.wait_for_timeout(500)

            await page.wait_for_timeout(800)

            if not payloads:
                raise XiaohongshuStatsSyncError("未拦截到小红书笔记列表接口，页面结构可能已变化", code=500)

            merged = merge_intercepted_payloads(payloads)
            if merged.get("success") is False and merged.get("code") not in (0, "0", None):
                raise XiaohongshuStatsSyncError(
                    f"小红书笔记列表返回异常: {merged.get('msg') or merged.get('code')}",
                    code=500,
                )

            items = parse_xiaohongshu_list_payload(merged, limit=limit)
            xiaohongshu_logger.info(f"小红书笔记同步完成: {len(items)} 条 (limit={limit})")
            return items
        finally:
            await browser.close()


def sync_recent_items_sync(account_file: str | Path, limit: int = 5, headless: bool | None = None) -> list[dict]:
    return asyncio.run(sync_recent_items(account_file, limit=limit, headless=headless))
