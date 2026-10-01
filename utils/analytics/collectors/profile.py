"""通过各平台现有创作者页面读取账号粉丝数和对应证据。"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from utils.analytics.service import AnalyticsError
from utils.analytics.store import nullable_count

CREATOR_URLS = {
    "douyin": "https://creator.douyin.com/",
    "kuaishou": "https://cp.kuaishou.com/",
    "xiaohongshu": "https://creator.xiaohongshu.com/",
    "bilibili": "https://member.bilibili.com/",
}
FOLLOWER_KEYS = ("follower_count", "followers_count", "fans_count", "fan_count",
                 "followerCount", "followersCount", "fansCount", "fanCount")
PROFILE_KEYS = {"user", "user_info", "userinfo", "userInfo", "profile", "account",
                "account_info", "accountInfo", "basic_info", "basicInfo", "user_data", "userData"}
IDENTITY_KEYS = {"uid", "user_id", "userId", "nickname", "nick_name", "username", "unique_id", "sec_uid"}
FOLLOWER_LABELS = ("粉丝数", "总粉丝", "粉丝总数", "粉丝", "关注者")


def extract_profile_followers(payload: dict) -> tuple[int | None, str | None]:
    """仅解析明确账号资料对象；不遍历作品列表、评论作者或任意数值字段。"""
    def visit(node, path, trusted=False, depth=0):
        if not isinstance(node, dict) or depth > 6:
            return None, None
        trusted = trusted or bool(IDENTITY_KEYS.intersection(node))
        if trusted:
            for key in FOLLOWER_KEYS:
                if key in node:
                    number = nullable_count(node[key])
                    if number is not None:
                        return number, ".".join([*path, key])
        for key, child in node.items():
            # 数组及作品/作者数据不会进入账号资料提取。
            if key in PROFILE_KEYS or key in {"data", "result", "response"}:
                result = visit(child, [*path, key], trusted or key in PROFILE_KEYS, depth + 1)
                if result[0] is not None:
                    return result
        return None, None

    return visit(payload, [])


def parse_label_count(text: str, label: str) -> int | None:
    """只接受完整精确数字；1.2 万等缩写不能伪装为精确粉丝数。"""
    compact = re.sub(r"[ \t\u00a0]", "", str(text or ""))
    number = r"([0-9]+|[0-9]{1,3}(?:[,，][0-9]{3})+)"
    pattern = rf"^(?:{re.escape(label)}[:：]?\n*{number}|{number}\n*{re.escape(label)})$"
    match = re.fullmatch(pattern, compact)
    if not match:
        return None
    raw = next(group for group in match.groups() if group is not None)
    return nullable_count(raw.replace(",", "").replace("，", ""))


def _public_url(url):
    """来源证据去除查询参数和片段，避免保存接口中的令牌。"""
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


async def collect_account_profile(account_file: str | Path, platform: str,
                                  headless: bool | None = None) -> dict:
    """读取已有登录态创作者首页；没有精确粉丝数据时返回明确缺失说明。"""
    if platform not in CREATOR_URLS:
        raise AnalyticsError("该平台暂未接入账号资料采集", 501)
    account_file = Path(account_file)
    if not account_file.is_file():
        raise AnalyticsError("登录会话不存在，请在账号管理中重新登录", 401)
    # 浏览器依赖延迟导入，使纯分析查询和单元测试不需要浏览器运行时。
    from patchright.async_api import async_playwright
    from conf import LOCAL_CHROME_HEADLESS, LOCAL_CHROME_PATH
    from utils.base_social_media import set_init_script
    from utils.browser_options import get_browser_options

    headless = LOCAL_CHROME_HEADLESS if headless is None else headless
    matches = []
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(**get_browser_options(headless, LOCAL_CHROME_PATH))
        try:
            context = await browser.new_context(storage_state=str(account_file))
            context = await set_init_script(context)
            page = await context.new_page()

            async def on_response(response):
                """只接收当前平台域名的成功 JSON，并保存必要的字段位置。"""
                domain = urlsplit(CREATOR_URLS[platform]).hostname.split(".")[-2:]
                host = urlsplit(response.url).hostname or ""
                if response.status != 200 or host.split(".")[-2:] != domain:
                    return
                try:
                    payload = await response.json()
                    number, field = extract_profile_followers(payload)
                    if number is not None:
                        matches.append({"kind": "profile_response", "url": _public_url(response.url),
                                        "field": field, "value": number})
                except Exception:
                    # 非 JSON 静态资源和未知结构不影响页面采集。
                    return

            page.on("response", on_response)
            await page.goto(CREATOR_URLS[platform], wait_until="domcontentloaded", timeout=60000)
            for _ in range(16):
                if matches:
                    break
                await page.wait_for_timeout(500)
            if not matches:
                for label in FOLLOWER_LABELS:
                    labels = page.get_by_text(label, exact=True)
                    for index in range(min(await labels.count(), 8)):
                        candidate = labels.nth(index)
                        if not await candidate.is_visible():
                            continue
                        # 最多检查两个近邻容器，不在整个页面任意拼凑账号统计值。
                        for level in ("..", "../.."):
                            text = await candidate.locator(f"xpath={level}").inner_text(timeout=2000)
                            number = parse_label_count(text, label)
                            if number is not None:
                                matches.append({"kind": "page_label", "url": _public_url(page.url),
                                                "field": label, "value": number})
                                break
                        if matches:
                            break
                    if matches:
                        break
            values = {entry["value"] for entry in matches}
            if len(values) > 1:
                return {"followerCount": None, "evidence": matches,
                        "warnings": ["页面返回多个不一致的粉丝数，未保存为账号粉丝指标"]}
            return {"followerCount": next(iter(values), None), "evidence": matches,
                    "warnings": [] if values else ["未在登录页面读取到精确粉丝数；请确认登录状态和平台页面权限"]}
        finally:
            await browser.close()


def collect_account_profile_sync(account_file: str | Path, platform: str,
                                 headless: bool | None = None) -> dict:
    """同步 Flask 路由入口，复用同一只读浏览器采集实现。"""
    return asyncio.run(collect_account_profile(account_file, platform, headless=headless))
