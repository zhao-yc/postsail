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
    from utils.platform_accounts import ACCOUNT_PLATFORMS, ACCOUNT_UNAVAILABLE_REASONS
    if type in ACCOUNT_UNAVAILABLE_REASONS:
        return False
    if type in ACCOUNT_PLATFORMS and type >= 12:
        return await cookie_auth_article_account(ACCOUNT_PLATFORMS[type], Path(BASE_DIR / "cookiesFile" / file_path))
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
    "yidian": {"url": "https://mp.yidianzixun.com/#/Writing/articleEditor", "host": "mp.yidianzixun.com",
               "identity_url": "https://mp.yidianzixun.com/api/new-user-task-info"},
    "dayu": {"url": "https://mp.dayu.com/dashboard/article/write", "host": "mp.dayu.com",
             "identity_script": "() => Boolean(window.globalConfig && (window.globalConfig.isLogin === true || window.globalConfig.isLogin === 'true') && window.globalConfig.wmid && window.globalConfig.utoken)"},
    "netease": {"url": "https://mp.163.com/subscribe_v4/index.html#/article-publish", "host": "mp.163.com",
                "identity_url": "https://mp.163.com/wemedia/navinfo.do"},
    "acfun": {"url": "https://www.acfun.cn/member", "host": "www.acfun.cn",
              "hosts": ("www.acfun.cn", "member.acfun.cn"),
              "identity_url": "https://www.acfun.cn/rest/pc-direct/user/personalBasicInfo"},
    "kuaichuan": {"url": "https://kuaichuan.360kuai.com/#/console/publish/article", "host": "kuaichuan.360kuai.com",
                  "title": 'textarea[placeholder="请输入标题"]',
                  "body": 'div[contenteditable="true"]',
                  "action": 'div.button_publish.item.editor-btn.editor-main-btn'},
    "xueqiu": {"url": "https://mp.xueqiu.com/writeV2", "host": "mp.xueqiu.com",
               "identity_script": "() => Boolean(window.UOM_CURRENTUSER && window.UOM_CURRENTUSER.currentUser && window.UOM_CURRENTUSER.currentUser.id)"},
    # 京东官方 RootApp 合并三项只读达人查询到 _gdata.user；账号页以 id 为 talentId、name 为昵称。
    # 只读取渲染后的身份，不请求发布接口，也不把普通京东 Cookie 或非空 user 对象当作已登录。
    "jingdong": {"url": "https://dr.jd.com/n/publish-article.html", "host": "dr.jd.com",
                 "identity_script": """() => {
                     const user = window._gdata?.user;
                     const id = user?.id;
                     const validId = (typeof id === 'number' || typeof id === 'string') && /^[1-9]\\d*$/.test(String(id));
                     return Boolean(validId && typeof user.name === 'string' && user.name.trim());
                 }"""},
    "douban": {"url": "https://www.douban.com/note/create", "host": "www.douban.com",
               "identity_script": "() => Boolean(window._USER_NAME && document.querySelector('input[name=note_id]')?.value && document.querySelector('input[name=ck]')?.value)"},
    "csdn": {"url": "https://mp.csdn.net/mp_blog/creation/editor", "host": "mp.csdn.net",
             "title": 'input[placeholder*="标题"], textarea[placeholder*="标题"]',
             "body": '.cke_editable[contenteditable="true"], .ProseMirror[contenteditable="true"], .ql-editor[contenteditable="true"], body[contenteditable="true"]',
             "body_frame": 'iframe.cke_wysiwyg_frame',
             "action": 'button:text-is("发布文章"), button:text-is("发布博客")'},
    "jianshu": {"url": "https://www.jianshu.com/writer", "host": "www.jianshu.com",
                "identity_url": "https://www.jianshu.com/settings/basic.json"},
    # 官方 main.3d7cceaf.js：creatorinfo 仅 returncode===0 时返回 result，长文面向 PGC/OGC。
    "chejiahao": {"url": "https://creator.autohome.com.cn/web",
                  "host": "creator.autohome.com.cn",
                  "identity_url": "https://creator.autohome.com.cn/openapi/ypttd/yjc/csc/creator/creatorinfo",
                  "identity_token_key": "__CREATRO_OA_TOKEN__"},
    # 官方 bitauto.login.version4.js：只有 get_message_num 返回 status==1 才设置 isLogined/userId。
    "yiche": {"url": "https://mp.yiche.com/", "host": "mp.yiche.com",
              "identity_script": """() => {
                  const account = window.Bitauto?.Login?.result;
                  const id = account?.userId;
                  return Boolean(account?.isLogined === true &&
                      (typeof id === 'number' || typeof id === 'string') && /^[1-9]\\d*$/.test(String(id)));
              }"""},
    # 官方 main.b2fb097b.js：用户查询成功后才写入 Garr.pgc_info；10014 失败会转登录。
    "dongchedi": {"url": "https://mp.dcdapp.com/profile_v2/", "host": "mp.dcdapp.com",
                  "identity_script": """() => {
                      const id = window.Garr?.pgc_info?.user?.id;
                      return Boolean((typeof id === 'number' || typeof id === 'string') &&
                          /^[1-9]\\d*$/.test(String(id)));
                  }"""},
}


def _article_probe_host_matches(url, probe):
    from urllib.parse import urlparse
    parsed = urlparse(url)
    # 单页应用也可能通过 hash 登录；禁止相似后缀域名及非 HTTPS 页面。
    route = (parsed.path + "/" + parsed.fragment).lower()
    return (parsed.scheme == "https" and parsed.hostname in probe.get("hosts", (probe["host"],))
            and not any(value in route for value in ("login", "signin", "sign_in", "userauth")))


async def _article_positive_identity(page, platform, probe, timeout):
    """只读页面身份或账号接口；浏览器 Cookie 的存在本身不构成登录证据。"""
    if probe.get("identity_script"):
        await page.wait_for_function(probe["identity_script"], timeout=timeout)
        return await page.evaluate(probe["identity_script"]) is True
    if not probe.get("identity_url"):
        return None
    headers = {"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}
    if probe.get("identity_token_key"):
        # 官方 OA 登录可用本地 token；不记录或返回凭据，仍以服务器身份响应判定。
        token = await page.evaluate("key => localStorage.getItem(key)", probe["identity_token_key"])
        if isinstance(token, str) and token:
            headers["Authorization"] = token
    response = await page.request.get(probe["identity_url"], timeout=timeout, headers=headers)
    identity_probe = {"host": probe["identity_host"]} if probe.get("identity_host") else probe
    if not response.ok or not _article_probe_host_matches(response.url, identity_probe):
        return False
    data = await response.json()
    if not isinstance(data, dict):
        return False
    if platform == "yidian":
        result = data.get("result")
        return data.get("status") == "success" and isinstance(result, dict) and bool(result.get("mediaId"))
    if platform == "netease":
        account = data.get("data")
        return data.get("code") == 1 and isinstance(account, dict) and bool(account.get("wemediaId"))
    if platform == "jianshu":
        account = data.get("data", data)
        return isinstance(account, dict) and bool(account.get("nickname") or account.get("name"))
    if platform == "acfun":
        account = data.get("info")
        return isinstance(account, dict) and bool(account.get("userId"))
    if platform == "chejiahao":
        account = data.get("result")
        return (type(data.get("returncode")) is int and data["returncode"] == 0 and
                isinstance(account, dict) and _article_account_id_is_valid(account.get("userid")) and
                account.get("role") in (2, 3, "2", "3"))
    return False


def _article_account_id_is_valid(value):
    """作者接口必须返回明确 ID；拒绝布尔值、占位文本或失败时的零值。"""
    import re
    if type(value) is int:
        return value > 0
    if isinstance(value, str):
        return bool(re.fullmatch(r"[1-9][0-9]*", value))
    return False


async def _article_editor_is_ready(page, probe, timeout):
    """标题、正文和发布操作均须可见；不为检查登录点击新建、保存或发布。"""
    for name in ("title", "body"):
        matches = page.locator(probe[name])
        if name == "body" and probe.get("body_frame") and await page.locator(probe["body_frame"]).count() == 1:
            matches = page.frame_locator(probe["body_frame"]).locator(probe[name])
        await matches.first.wait_for(state="attached", timeout=timeout)
        editable = 0
        for index in range(await matches.count()):
            candidate = matches.nth(index)
            if await candidate.is_visible() and await candidate.is_editable():
                editable += 1
        if editable != 1:
            return False
    await page.locator(probe["action"]).first.wait_for(state="visible", timeout=timeout)
    return True


async def article_account_is_logged_in(page, platform, timeout=10_000):
    """必须同时命中平台后台域名和正向编辑器或导航标识，避免超时误判成功。"""
    probe = ARTICLE_LOGIN_PROBES[platform]
    try:
        if not _article_probe_host_matches(page.url, probe):
            return False
        if platform not in {"weibo", "qiehao"}:
            identity = await _article_positive_identity(page, platform, probe, timeout)
            if identity is None:
                identity = await _article_editor_is_ready(page, probe, timeout)
            return identity is True and _article_probe_host_matches(page.url, probe)
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
        return _article_probe_host_matches(page.url, probe)
    except Exception:
        return False


async def cookie_auth_article_account(platform, account_file):
    """文章账号正向登录探测，只读页面与身份信息，不修改内容。"""
    from utils.articles.session import load_article_storage_state
    if platform not in ARTICLE_LOGIN_PROBES:
        return False
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
