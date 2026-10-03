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
        case 12:
            return await cookie_auth_article_account("wechat", Path(BASE_DIR / "cookiesFile" / file_path))
        case 13:
            return await cookie_auth_article_account("jd", Path(BASE_DIR / "cookiesFile" / file_path))
        case 14:
            return await cookie_auth_article_account("xiaohongshu_merchant", Path(BASE_DIR / "cookiesFile" / file_path))
        case 15:
            return await cookie_auth_article_account("dongchedi", Path(BASE_DIR / "cookiesFile" / file_path))
        case 16:
            return await cookie_auth_article_account("taobao", Path(BASE_DIR / "cookiesFile" / file_path))
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
    "wechat": {"url": "https://mp.weixin.qq.com/", "host": "mp.weixin.qq.com",
               "selector": '#menuBar a[href*="/cgi-bin/appmsg"]:visible, '
                           '#menuBar a[href*="/cgi-bin/appmsgpublish"]:visible, '
                           '.weui-desktop-layout__side a[href*="/cgi-bin/appmsg"]:visible, '
                           'a[href*="action=logout"]:visible'},
    # 京东官方创作者前端在成功查询达人资料后写入 _gdata.user。
    "jd": {"url": "https://dr.jd.com/n/home.html", "host": "dr.jd.com", "path_prefix": "/n/",
           "script": "() => { const user = window._gdata && window._gdata.user; "
                     "return !!(user && String(user.id || '').trim() && "
                     "typeof user.pin === 'string' && user.pin.trim()); }"},
    # 商家店铺后台必须有店名；个人 creator 后台和 customer 登录页均不能通过。
    "xiaohongshu_merchant": {"url": "https://ark.xiaohongshu.com/ark/home", "host": "ark.xiaohongshu.com",
                            "selectors": ['.store-name:visible'], "text_selector": '.store-name:visible'},
    "dongchedi": {"url": "https://mp.dcdapp.com/profile_v2/publish/article", "host": "mp.dcdapp.com",
                  "path": "/profile_v2/publish/article",
                  "selectors": ['textarea:visible', 'button.publish-btn:text-is("预览并发布"):visible',
                                'div[contenteditable="true"]:visible, iframe[id^="ueditor_"]:visible']},
    "taobao": {"url": "https://creator.guanghe.taobao.com/", "host": "creator.guanghe.taobao.com",
               "selectors": ['img[data-autolog-container="user_content_account"]:visible',
                             '[data-autolog*="text=用户模块-账号管理"]:visible',
                             '[data-autolog*="text=发布作品"]:visible'],
               "text_selector": '[data-autolog*="text=用户模块-账号管理"]:visible',
               "text_exclusions": {"账号正常", "逛逛号", "账号管理"}},
}


def _article_probe_location_matches(url, platform, probe):
    """登录地址与后台地址共用域名时，仍须验证路径和平台要求的令牌。"""
    from urllib.parse import parse_qs, urlparse
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != probe["host"]:
        return False
    if any(value in (parsed.path + "#" + parsed.fragment).lower() for value in ("login", "signin", "userauth")):
        return False
    if probe.get("path") and parsed.path.rstrip("/") != probe["path"]:
        return False
    if probe.get("path_prefix") and not parsed.path.startswith(probe["path_prefix"]):
        return False
    if platform == "wechat":
        token = parse_qs(parsed.query).get("token", [""])[0]
        if not parsed.path.startswith("/cgi-bin/") or not token.isascii() or not token.isdigit() or int(token) == 0:
            return False
    return True


async def article_account_is_logged_in(page, platform, timeout=10_000):
    """必须同时命中平台后台域名和正向编辑器或导航标识，避免超时误判成功。"""
    probe = ARTICLE_LOGIN_PROBES[platform]
    try:
        if not _article_probe_location_matches(page.url, platform, probe):
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
        elif platform in {"jd", "xiaohongshu_merchant", "dongchedi", "taobao"}:
            if probe.get("script"):
                await page.wait_for_function(probe["script"], timeout=timeout)
            for selector in probe.get("selectors", []):
                await page.locator(selector).first.wait_for(state="visible", timeout=timeout)
            if probe.get("text_selector"):
                field = page.locator(probe["text_selector"])
                if await field.count() != 1:
                    return False
                lines = (await field.first.inner_text()).splitlines()
                if not any(line.strip() and line.strip() not in probe.get("text_exclusions", set()) for line in lines):
                    return False
            challenge = page.locator('iframe[src*="captcha"]:visible, iframe[src*="geetest"]:visible, '
                                     '[role="dialog"]:has-text("请完成验证"):visible, '
                                     '[role="dialog"]:has-text("安全验证"):visible')
            if await challenge.count():
                return False
        else:
            # 只接受后台导航/账号操作，公开首页的宣传文字不能通过。
            await page.locator(probe["selector"]).first.wait_for(state="visible", timeout=timeout)
        return _article_probe_location_matches(page.url, platform, probe)
    except Exception:
        return False


async def cookie_auth_article_account(platform, account_file):
    """独立文章账号正向登录探测，仅访问后台页面，不修改内容。"""
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
