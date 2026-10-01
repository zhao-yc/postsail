import asyncio
import configparser
import os

from playwright.async_api import async_playwright
from xhs import XhsClient

from conf import BASE_DIR, LOCAL_CHROME_HEADLESS, LOCAL_CHROME_PATH
from utils.browser_options import get_browser_options
from utils.base_social_media import set_init_script
from utils.log import tencent_logger, kuaishou_logger, douyin_logger
from pathlib import Path
from uploader.xhs_uploader.main import sign_local


async def cookie_auth_douyin(account_file):
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(**get_browser_options(LOCAL_CHROME_HEADLESS, LOCAL_CHROME_PATH))
        context = await browser.new_context(storage_state=account_file)
        context = await set_init_script(context)
        # 创建一个新的页面
        page = await context.new_page()
        # 访问指定的 URL
        await page.goto("https://creator.douyin.com/creator-micro/content/upload")
        try:
            await page.wait_for_url("https://creator.douyin.com/creator-micro/content/upload", timeout=5000)
            # 2024.06.17 抖音创作者中心改版
            # 判断
            # 等待“扫码登录”元素出现，超时 5 秒（如果 5 秒没出现，说明 cookie 有效）
            try:
                await page.get_by_text("扫码登录").wait_for(timeout=5000)
                douyin_logger.error("[+] cookie 失效，需要扫码登录")
                return False
            except:
                douyin_logger.success("[+]  cookie 有效")
                return True
        except:
            douyin_logger.error("[+] 等待5秒 cookie 失效")
            await context.close()
            await browser.close()
            return False


async def cookie_auth_tencent(account_file):
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(**get_browser_options(LOCAL_CHROME_HEADLESS, LOCAL_CHROME_PATH))
        context = await browser.new_context(storage_state=account_file)
        context = await set_init_script(context)
        # 创建一个新的页面
        page = await context.new_page()
        # 访问指定的 URL
        await page.goto("https://channels.weixin.qq.com/platform/post/create")
        try:
            await page.wait_for_selector('div.title-name:has-text("微信小店")', timeout=5000)  # 等待5秒
            tencent_logger.error("[+] 等待5秒 cookie 失效")
            return False
        except:
            tencent_logger.success("[+] cookie 有效")
            return True


async def cookie_auth_ks(account_file):
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(**get_browser_options(LOCAL_CHROME_HEADLESS, LOCAL_CHROME_PATH))
        context = await browser.new_context(storage_state=account_file)
        context = await set_init_script(context)
        # 创建一个新的页面
        page = await context.new_page()
        # 访问指定的 URL
        await page.goto("https://cp.kuaishou.com/article/publish/video")
        try:
            await page.wait_for_selector("div.names div.container div.name:text('机构服务')", timeout=5000)  # 等待5秒

            kuaishou_logger.info("[+] 等待5秒 cookie 失效")
            return False
        except:
            kuaishou_logger.success("[+] cookie 有效")
            return True


async def cookie_auth_xhs(account_file):
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(**get_browser_options(LOCAL_CHROME_HEADLESS, LOCAL_CHROME_PATH))
        context = await browser.new_context(storage_state=account_file)
        context = await set_init_script(context)
        # 创建一个新的页面
        page = await context.new_page()
        # 访问指定的 URL
        await page.goto("https://creator.xiaohongshu.com/creator-micro/content/upload")
        try:
            await page.wait_for_url("https://creator.xiaohongshu.com/creator-micro/content/upload", timeout=5000)
        except:
            print("[+] 等待5秒 cookie 失效")
            await context.close()
            await browser.close()
            return False
        # 2024.06.17 抖音创作者中心改版
        if await page.get_by_text('手机号登录').count() or await page.get_by_text('扫码登录').count():
            print("[+] 等待5秒 cookie 失效")
            return False
        else:
            print("[+] cookie 有效")
            return True


async def cookie_auth_baijiahao(account_file):
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(**get_browser_options(LOCAL_CHROME_HEADLESS, LOCAL_CHROME_PATH))
        context = await browser.new_context(storage_state=account_file)
        context = await set_init_script(context)
        page = await context.new_page()
        await page.goto("https://baijiahao.baidu.com/builder/rc/home")
        await page.wait_for_timeout(timeout=5000)
        if await page.get_by_text('注册/登录百家号').count():
            print("[+] 百家号 cookie 失效")
            return False
        else:
            print("[+] 百家号 cookie 有效")
            return True


async def cookie_auth_toutiao(account_file):
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(**get_browser_options(LOCAL_CHROME_HEADLESS, LOCAL_CHROME_PATH))
        context = await browser.new_context(storage_state=account_file)
        context = await set_init_script(context)
        page = await context.new_page()
        await page.goto("https://mp.toutiao.com/")
        await page.wait_for_timeout(timeout=5000)
        url = page.url
        if "/auth/page/login" in url or "sso.toutiao.com" in url:
            print("[+] 今日头条 cookie 失效")
            return False
        if "/profile_v4" in url:
            print("[+] 今日头条 cookie 有效")
            return True
        # 兜底：侧栏/发布入口
        if await page.locator('a[href*="upload-video"], a[href*="graphic/publish"]').count():
            print("[+] 今日头条 cookie 有效")
            return True
        print("[+] 今日头条 cookie 失效")
        return False


async def cookie_auth_sohu(account_file):
    from uploader.sohu_uploader.main import cookie_auth as sohu_cookie_auth
    return await sohu_cookie_auth(account_file)


async def cookie_auth_zhihu(account_file):
    from uploader.zhihu_uploader.main import cookie_auth as zhihu_cookie_auth
    return await zhihu_cookie_auth(account_file)


async def check_cookie(type, file_path):
    match type:
        # 小红书
        case 1:
            return await cookie_auth_xhs(Path(BASE_DIR / "cookiesFile" / file_path))
        # 视频号
        case 2:
            return await cookie_auth_tencent(Path(BASE_DIR / "cookiesFile" / file_path))
        # 抖音
        case 3:
            return await cookie_auth_douyin(Path(BASE_DIR / "cookiesFile" / file_path))
        # 快手
        case 4:
            return await cookie_auth_ks(Path(BASE_DIR / "cookiesFile" / file_path))
        # 百家号
        case 5:
            return await cookie_auth_baijiahao(Path(BASE_DIR / "cookiesFile" / file_path))
        # Bilibili
        case 6:
            return await cookie_auth_bilibili(Path(BASE_DIR / "cookiesFile" / file_path))
        # 今日头条
        case 7:
            return await cookie_auth_toutiao(Path(BASE_DIR / "cookiesFile" / file_path))
        # 搜狐号
        case 8:
            return await cookie_auth_sohu(Path(BASE_DIR / "cookiesFile" / file_path))
        # 知乎
        case 9:
            return await cookie_auth_zhihu(Path(BASE_DIR / "cookiesFile" / file_path))
        # 微博与企鹅号分别使用独立账号，不能复用视频号类型 2。
        case 10:
            return await cookie_auth_article_account("weibo", Path(BASE_DIR / "cookiesFile" / file_path))
        case 11:
            return await cookie_auth_article_account("qiehao", Path(BASE_DIR / "cookiesFile" / file_path))
        case _:
            return False


ARTICLE_LOGIN_PROBES = {
    "weibo": {"url": "https://card.weibo.com/article/v3/editor", "host": "card.weibo.com",
              "selector": 'textarea[placeholder="请输入标题"], .ProseMirror[contenteditable="true"]'},
    "qiehao": {"url": "https://om.qq.com/main/creation/article", "host": "om.qq.com",
               "selector": 'nav a:text-is("内容管理"):visible, aside a:text-is("内容管理"):visible, '
                           '[role="menuitem"]:text-is("内容管理"):visible, '
                           '[class*="sidebar"] a:text-is("内容管理"):visible, '
                           'a:text-is("退出登录"):visible, button:text-is("退出登录"):visible, '
                           '[role="menuitem"]:text-is("退出登录"):visible'},
}


async def article_account_is_logged_in(page, platform, timeout=10_000):
    """必须同时命中平台后台域名和正向编辑器或导航标识，避免超时误判成功。"""
    from urllib.parse import urlparse
    probe = ARTICLE_LOGIN_PROBES[platform]
    try:
        parsed = urlparse(page.url)
        if parsed.hostname != probe["host"] or any(value in parsed.path.lower() for value in ("login", "signin", "userauth")):
            return False
        if platform == "weibo":
            import re
            # 入口首先展示已认证的草稿列表；校验只读列表，不能为查登录创建新草稿。
            editors = page.locator(probe["selector"])
            if await editors.count() and await editors.first.is_visible():
                pass
            else:
                write = page.locator('button, a, [role="button"]').filter(has_text=re.compile(r"^写文章$"))
                await write.first.wait_for(state="visible", timeout=timeout)
                drafts = page.get_by_text(re.compile(r"^(?:我的)?草稿(?:箱|管理)?(?:\s*[（(]\d+[）)])?$"))
                await drafts.first.wait_for(state="visible", timeout=timeout)
        else:
            # 企鹅号只接受后台导航/账号操作，公开首页的「内容管理」宣传文字不能通过。
            await page.locator(probe["selector"]).first.wait_for(state="visible", timeout=timeout)
        parsed = urlparse(page.url)
        return parsed.hostname == probe["host"] and not any(value in parsed.path.lower() for value in ("login", "signin", "userauth"))
    except Exception:
        return False


async def cookie_auth_article_account(platform, account_file):
    """微博与企鹅号正向登录探测，仅访问编辑页，不修改内容。"""
    from utils.articles.session import load_article_storage_state
    browser = None
    try:
        state = load_article_storage_state(platform, account_file)
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(**get_browser_options(LOCAL_CHROME_HEADLESS, LOCAL_CHROME_PATH))
            try:
                context = await browser.new_context(storage_state=state)
                page = await context.new_page()
                await page.goto(ARTICLE_LOGIN_PROBES[platform]["url"], wait_until="domcontentloaded", timeout=60_000)
                return await article_account_is_logged_in(page, platform)
            finally:
                await browser.close()
    except Exception:
        # 结构、浏览器依赖、网络或登录失败都不能视为有效会话，也不输出凭据内容。
        print(f"[+] {platform} 会话校验失败，请重新登录或检查浏览器配置")
        return False


async def cookie_auth_bilibili(account_file):
    """用平台只读登录接口确认会话，兼容标准 state 和 biliup 且不刷新或改写文件。"""
    from utils.articles.session import load_article_storage_state
    try:
        state = load_article_storage_state("bilibili", account_file)
        async with async_playwright() as playwright:
            context = await playwright.request.new_context(storage_state=state)
            try:
                response = await context.get("https://api.bilibili.com/x/web-interface/nav", timeout=30_000)
                if not response.ok:
                    return False
                result = await response.json()
                return result.get("code") == 0 and result.get("data", {}).get("isLogin") is True
            finally:
                await context.dispose()
    except Exception:
        print("[+] Bilibili 会话校验失败，请重新登录")
        return False

# a = asyncio.run(check_cookie(1,"3a6cfdc0-3d51-11f0-8507-44e51723d63c.json"))
# print(a)
