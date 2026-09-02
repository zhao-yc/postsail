import asyncio
import configparser
import os

from playwright.async_api import async_playwright
from xhs import XhsClient

from conf import BASE_DIR, LOCAL_CHROME_HEADLESS
from utils.base_social_media import set_init_script
from utils.log import tencent_logger, kuaishou_logger, douyin_logger
from pathlib import Path
from uploader.xhs_uploader.main import sign_local


async def cookie_auth_douyin(account_file):
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=LOCAL_CHROME_HEADLESS)
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
        browser = await playwright.chromium.launch(headless=LOCAL_CHROME_HEADLESS)
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
        browser = await playwright.chromium.launch(headless=LOCAL_CHROME_HEADLESS)
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
        browser = await playwright.chromium.launch(headless=LOCAL_CHROME_HEADLESS)
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
        browser = await playwright.chromium.launch(headless=LOCAL_CHROME_HEADLESS)
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
        browser = await playwright.chromium.launch(headless=LOCAL_CHROME_HEADLESS)
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
        case _:
            return False


async def cookie_auth_bilibili(account_file):
    """通过biliup CLI验证Bilibili cookie是否有效"""
    from uploader.bilibili_uploader.runtime import run_biliup_command
    if not account_file.exists():
        print("[+] Bilibili cookie 文件不存在")
        return False
    result = run_biliup_command(["-u", str(account_file), "renew"])
    if result.returncode == 0:
        print("[+] Bilibili cookie 有效")
        return True
    else:
        print("[+] Bilibili cookie 失效")
        return False

# a = asyncio.run(check_cookie(1,"3a6cfdc0-3d51-11f0-8507-44e51723d63c.json"))
# print(a)
