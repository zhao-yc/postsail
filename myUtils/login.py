import asyncio
import sqlite3

from playwright.async_api import TimeoutError as PlaywrightTimeoutError, async_playwright

from myUtils.auth import check_cookie
from utils.base_social_media import set_init_script
import uuid
from pathlib import Path
from conf import BASE_DIR, LOCAL_CHROME_HEADLESS, LOCAL_CHROME_PATH
from uploader.bilibili_uploader.runtime import run_biliup_command

# 统一获取浏览器启动配置（防风控+引入本地浏览器）
def get_browser_options():
    options = {
        'headless': LOCAL_CHROME_HEADLESS,
        'args': [
            '--disable-blink-features=AutomationControlled',  # 核心防爬屏蔽：去掉 window.navigator.webdriver 标签
            '--lang=zh-CN',
            '--disable-infobars',
            '--start-maximized'
        ]
    }
    # 如果用户在 conf.py 里配置了本地 Chrome，就用本地的，这样成功率极高
    if LOCAL_CHROME_PATH:
        options['executable_path'] = LOCAL_CHROME_PATH
    else:
        # 未配置路径时使用系统已安装的 Chrome，避免 Playwright Chromium 未安装导致启动失败
        options['channel'] = 'chrome'

    return options

# 等待二维码图片的 src 就绪（页面渲染慢时立即读取会拿到空值，导致前端一直停留在"请求中"）
async def wait_for_qr_src(locator, timeout_s: int = 60):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while True:
        try:
            src = await locator.get_attribute("src", timeout=5000)
        except Exception:
            src = None
        if src:
            return src
        if loop.time() >= deadline:
            return None
        await asyncio.sleep(1)

# 抖音登录
async def douyin_cookie_gen(id,status_queue):
    url_changed_event = asyncio.Event()
    async def on_url_change():
        # 检查是否是主框架的变化
        if page.url != original_url:
            url_changed_event.set()
    async with async_playwright() as playwright:
        options = get_browser_options()
        # Make sure to run headed.
        browser = await playwright.chromium.launch(**options)
        # Setup context however you like.
        context = await browser.new_context()  # Pass any options
        context = await set_init_script(context)
        # Pause the page, and start recording manually.
        page = await context.new_page()
        await page.goto("https://creator.douyin.com/")
        original_url = page.url
        img_locator = page.get_by_role("img", name="二维码")
        src = await wait_for_qr_src(img_locator)
        if not src:
            print("❌ 抖音二维码加载超时")
            await page.close()
            await context.close()
            await browser.close()
            status_queue.put("500")
            return None
        print("✅ 图片地址:", src)
        status_queue.put(src)
        # 监听页面的 'framenavigated' 事件，只关注主框架的变化
        page.on('framenavigated',
                lambda frame: asyncio.create_task(on_url_change()) if frame == page.main_frame else None)
        try:
            # 等待 URL 变化或超时
            await asyncio.wait_for(url_changed_event.wait(), timeout=200)  # 最多等待 200 秒
            print("监听页面跳转成功")
        except asyncio.TimeoutError:
            print("监听页面跳转超时")
            await page.close()
            await context.close()
            await browser.close()
            status_queue.put("500")
            return None
        uuid_v1 = uuid.uuid1()
        print(f"UUID v1: {uuid_v1}")
        # 确保cookiesFile目录存在
        cookies_dir = Path(BASE_DIR / "cookiesFile")
        cookies_dir.mkdir(exist_ok=True)
        await context.storage_state(path=cookies_dir / f"{uuid_v1}.json")
        result = await check_cookie(3, f"{uuid_v1}.json")
        if not result:
            status_queue.put("500")
            await page.close()
            await context.close()
            await browser.close()
            return None
        await page.close()
        await context.close()
        await browser.close()
        with sqlite3.connect(Path(BASE_DIR / "db" / "database.db")) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                                INSERT INTO user_info (type, filePath, userName, status)
                                VALUES (?, ?, ?, ?)
                                ''', (3, f"{uuid_v1}.json", id, 1))
            conn.commit()
            print("✅ 用户状态已记录")
        status_queue.put("200")


# 视频号登录
async def get_tencent_cookie(id,status_queue):
    url_changed_event = asyncio.Event()
    async def on_url_change():
        # 检查是否是主框架的变化
        if page.url != original_url:
            url_changed_event.set()

    async with async_playwright() as playwright:
        options = get_browser_options()
        # Make sure to run headed.
        browser = await playwright.chromium.launch(**options)
        # Setup context however you like.
        context = await browser.new_context()  # Pass any options
        # Pause the page, and start recording manually.
        context = await set_init_script(context)
        page = await context.new_page()
        await page.goto(
            "https://channels.weixin.qq.com",
            wait_until="commit",
            timeout=60_000,
        )
        original_url = page.url

        # 监听页面的 'framenavigated' 事件，只关注主框架的变化
        page.on('framenavigated',
                lambda frame: asyncio.create_task(on_url_change()) if frame == page.main_frame else None)

        # 等待 iframe 和二维码出现，避免页面刚打开时取到空元素
        iframe_element = page.locator("iframe").first
        await iframe_element.wait_for(state="attached", timeout=60_000)
        iframe_locator = page.frame_locator("iframe").first

        # 获取 iframe 中的第一个 img 元素
        img_locator = iframe_locator.get_by_role("img").first
        await img_locator.wait_for(state="visible", timeout=60_000)

        # 获取 src 属性值
        src = await img_locator.get_attribute("src")
        if not src:
            raise RuntimeError("视频号登录二维码未加载")
        if src.startswith("/"):
            src = f"https://open.weixin.qq.com{src}"
        print("✅ 图片地址:", src)
        status_queue.put(src)

        try:
            # 等待 URL 变化或超时
            await asyncio.wait_for(url_changed_event.wait(), timeout=200)  # 最多等待 200 秒
            print("监听页面跳转成功")
            # 扫码确认后先跳 login.html 做票据交换，再重定向进 /platform/ 并种下会话 cookie；
            # 必须等真正进入平台页再保存 storage_state，否则存出的是无效会话
            try:
                # 只等导航提交（commit）即可，会话 cookie 随跳转响应种下；
                # 默认等 load 会因创作者后台资源加载慢而误超时
                await page.wait_for_url("**/platform/**", wait_until="commit", timeout=30_000)
                print("✅ 已进入创作者平台，会话已建立")
                await page.wait_for_timeout(2000)  # 留点时间让 cookie 完全落定
            except (asyncio.TimeoutError, PlaywrightTimeoutError):
                print(f"⚠️ 扫码后未进入 /platform/，当前 URL: {page.url}")
        except asyncio.TimeoutError:
            status_queue.put("500")
            print("监听页面跳转超时")
            await page.close()
            await context.close()
            await browser.close()
            return None
        uuid_v1 = uuid.uuid1()
        print(f"UUID v1: {uuid_v1}")
        # 确保cookiesFile目录存在
        cookies_dir = Path(BASE_DIR / "cookiesFile")
        cookies_dir.mkdir(exist_ok=True)
        await context.storage_state(path=cookies_dir / f"{uuid_v1}.json")
        result = await check_cookie(2,f"{uuid_v1}.json")
        if not result:
            status_queue.put("500")
            await page.close()
            await context.close()
            await browser.close()
            return None
        await page.close()
        await context.close()
        await browser.close()

        with sqlite3.connect(Path(BASE_DIR / "db" / "database.db")) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                                INSERT INTO user_info (type, filePath, userName, status)
                                VALUES (?, ?, ?, ?)
                                ''', (2, f"{uuid_v1}.json", id, 1))
            conn.commit()
            print("✅ 用户状态已记录")
        status_queue.put("200")

# 快手登录
async def get_ks_cookie(id,status_queue):
    url_changed_event = asyncio.Event()
    async def on_url_change():
        # 检查是否是主框架的变化
        if page.url != original_url:
            url_changed_event.set()
    async with async_playwright() as playwright:
        options = {
            'args': [
                '--lang en-GB'
            ],
            'headless': LOCAL_CHROME_HEADLESS,  # Set headless option here
        }
        # Make sure to run headed.
        browser = await playwright.chromium.launch(**options)
        # Setup context however you like.
        context = await browser.new_context()  # Pass any options
        context = await set_init_script(context)
        # Pause the page, and start recording manually.
        page = await context.new_page()
        await page.goto("https://cp.kuaishou.com")

        # 定位并点击“立即登录”按钮（类型为 link）
        await page.get_by_role("link", name="立即登录").click()
        await page.get_by_text("扫码登录").click()
        img_locator = page.get_by_role("img", name="qrcode")
        src = await wait_for_qr_src(img_locator)
        if not src:
            print("❌ 快手二维码加载超时")
            await page.close()
            await context.close()
            await browser.close()
            status_queue.put("500")
            return None
        original_url = page.url
        print("✅ 图片地址:", src)
        status_queue.put(src)
        # 监听页面的 'framenavigated' 事件，只关注主框架的变化
        page.on('framenavigated',
                lambda frame: asyncio.create_task(on_url_change()) if frame == page.main_frame else None)

        try:
            # 等待 URL 变化或超时
            await asyncio.wait_for(url_changed_event.wait(), timeout=200)  # 最多等待 200 秒
            print("监听页面跳转成功")
        except asyncio.TimeoutError:
            status_queue.put("500")
            print("监听页面跳转超时")
            await page.close()
            await context.close()
            await browser.close()
            return None
        uuid_v1 = uuid.uuid1()
        print(f"UUID v1: {uuid_v1}")
        # 确保cookiesFile目录存在
        cookies_dir = Path(BASE_DIR / "cookiesFile")
        cookies_dir.mkdir(exist_ok=True)
        await context.storage_state(path=cookies_dir / f"{uuid_v1}.json")
        result = await check_cookie(4, f"{uuid_v1}.json")
        if not result:
            status_queue.put("500")
            await page.close()
            await context.close()
            await browser.close()
            return None
        await page.close()
        await context.close()
        await browser.close()

        with sqlite3.connect(Path(BASE_DIR / "db" / "database.db")) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                                        INSERT INTO user_info (type, filePath, userName, status)
                                        VALUES (?, ?, ?, ?)
                                        ''', (4, f"{uuid_v1}.json", id, 1))
            conn.commit()
            print("✅ 用户状态已记录")
        status_queue.put("200")

# 小红书登录
async def xiaohongshu_cookie_gen(id,status_queue):
    url_changed_event = asyncio.Event()

    async def on_url_change():
        # 检查是否是主框架的变化
        if page.url != original_url:
            url_changed_event.set()

    async with async_playwright() as playwright:
        options = {
            'args': [
                '--lang en-GB'
            ],
            'headless': LOCAL_CHROME_HEADLESS,  # Set headless option here
        }
        # Make sure to run headed.
        browser = await playwright.chromium.launch(**options)
        # Setup context however you like.
        context = await browser.new_context()  # Pass any options
        context = await set_init_script(context)
        # Pause the page, and start recording manually.
        page = await context.new_page()
        await page.goto("https://creator.xiaohongshu.com/")
        await page.locator('img.css-wemwzq').click()

        img_locator = page.get_by_role("img").nth(2)
        src = await wait_for_qr_src(img_locator)
        if not src:
            print("❌ 小红书二维码加载超时")
            await page.close()
            await context.close()
            await browser.close()
            status_queue.put("500")
            return None
        original_url = page.url
        print("✅ 图片地址:", src)
        status_queue.put(src)
        # 监听页面的 'framenavigated' 事件，只关注主框架的变化
        page.on('framenavigated',
                lambda frame: asyncio.create_task(on_url_change()) if frame == page.main_frame else None)

        try:
            # 等待 URL 变化或超时
            await asyncio.wait_for(url_changed_event.wait(), timeout=200)  # 最多等待 200 秒
            print("监听页面跳转成功")
        except asyncio.TimeoutError:
            status_queue.put("500")
            print("监听页面跳转超时")
            await page.close()
            await context.close()
            await browser.close()
            return None
        uuid_v1 = uuid.uuid1()
        print(f"UUID v1: {uuid_v1}")
        # 确保cookiesFile目录存在
        cookies_dir = Path(BASE_DIR / "cookiesFile")
        cookies_dir.mkdir(exist_ok=True)
        await context.storage_state(path=cookies_dir / f"{uuid_v1}.json")
        result = await check_cookie(1, f"{uuid_v1}.json")
        if not result:
            status_queue.put("500")
            await page.close()
            await context.close()
            await browser.close()
            return None
        await page.close()
        await context.close()
        await browser.close()

        with sqlite3.connect(Path(BASE_DIR / "db" / "database.db")) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                           INSERT INTO user_info (type, filePath, userName, status)
                           VALUES (?, ?, ?, ?)
                           ''', (1, f"{uuid_v1}.json", id, 1))
            conn.commit()
            print("✅ 用户状态已记录")
        status_queue.put("200")

# 百家号登录（手动登录，非二维码）
async def baijiahao_cookie_gen(id, status_queue):
    browser = None
    context = None
    page = None
    try:
        status_queue.put("MANUAL_LOGIN")
        print(f"🟢 开始百家号登录: id={id}")
        async with async_playwright() as playwright:
            options = get_browser_options()
            options['headless'] = False
            browser = await playwright.chromium.launch(**options)
            context = await browser.new_context()
            context = await set_init_script(context)
            page = await context.new_page()
            await page.goto(
                "https://baijiahao.baidu.com/builder/theme/bjh/login",
                timeout=60000,
                wait_until="domcontentloaded",
            )
            print(f"🟢 百家号登录页已打开: {page.url}")
            try:
                await page.wait_for_url(
                    "https://baijiahao.baidu.com/builder/rc/**",
                    timeout=200_000,
                )
                print("✅ 百家号登录成功，检测到页面跳转")
            except asyncio.TimeoutError:
                print("❌ 百家号登录超时")
                status_queue.put("500")
                return None

            uuid_v1 = uuid.uuid1()
            print(f"UUID v1: {uuid_v1}")
            cookies_dir = Path(BASE_DIR / "cookiesFile")
            cookies_dir.mkdir(exist_ok=True)
            await context.storage_state(path=cookies_dir / f"{uuid_v1}.json")

            result = await check_cookie(5, f"{uuid_v1}.json")
            if not result:
                print("⚠️ cookie 即时校验未通过，仍保存账号，请稍后刷新验证")

            with sqlite3.connect(Path(BASE_DIR / "db" / "database.db")) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO user_info (type, filePath, userName, status)
                    VALUES (?, ?, ?, ?)
                ''', (5, f"{uuid_v1}.json", id, 1 if result else 0))
                conn.commit()
                print("✅ 百家号用户状态已记录")
            status_queue.put("200")
            return True
    except Exception as e:
        print(f"❌ 百家号登录异常: {e}")
        import traceback
        traceback.print_exc()
        try:
            status_queue.put("500")
        except Exception:
            pass
        return None
    finally:
        try:
            if page:
                await page.close()
        except Exception:
            pass
        try:
            if context:
                await context.close()
        except Exception:
            pass
        try:
            if browser:
                await browser.close()
        except Exception:
            pass


# 今日头条登录（扫码/手动，非二维码 SSE 推送，与百家号类似）
async def toutiao_cookie_gen(id, status_queue):
    browser = None
    context = None
    page = None
    try:
        # 尽早通知前端进入「手动登录」态，避免浏览器启动慢时一直转圈
        status_queue.put("MANUAL_LOGIN")
        print(f"🟢 开始今日头条登录: id={id}")
        async with async_playwright() as playwright:
            # 登录必须有头模式，方便用户扫码
            options = get_browser_options()
            options['headless'] = False
            print(f"🟢 启动浏览器 options={ {k: v for k, v in options.items() if k != 'args'} }")
            browser = await playwright.chromium.launch(**options)
            context = await browser.new_context()
            context = await set_init_script(context)
            page = await context.new_page()
            print("🟢 打开今日头条登录页...")
            await page.goto("https://mp.toutiao.com/auth/page/login", timeout=60000, wait_until="domcontentloaded")
            print(f"🟢 登录页已打开: {page.url}")
            try:
                # Playwright 的 callable 参数可能是 URL 对象，统一转 str
                await page.wait_for_url(
                    lambda url: ("/profile_v4" in str(url)) and ("/auth/page/login" not in str(url)),
                    timeout=200_000,
                )
                print("✅ 今日头条登录成功，检测到进入创作者后台")
            except asyncio.TimeoutError:
                print("❌ 今日头条登录超时")
                status_queue.put("500")
                return None

            uuid_v1 = uuid.uuid1()
            print(f"UUID v1: {uuid_v1}")
            cookies_dir = Path(BASE_DIR / "cookiesFile")
            cookies_dir.mkdir(exist_ok=True)
            await context.storage_state(path=cookies_dir / f"{uuid_v1}.json")

            # cookie 校验失败也不要卡死前端；仍写入账号，状态后续可再验证
            result = await check_cookie(7, f"{uuid_v1}.json")
            if not result:
                print("⚠️ cookie 即时校验未通过，仍保存账号，请稍后刷新验证")

            with sqlite3.connect(Path(BASE_DIR / "db" / "database.db")) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO user_info (type, filePath, userName, status)
                    VALUES (?, ?, ?, ?)
                ''', (7, f"{uuid_v1}.json", id, 1 if result else 0))
                conn.commit()
                print("✅ 今日头条用户状态已记录")
            status_queue.put("200")
            return True
    except Exception as e:
        print(f"❌ 今日头条登录异常: {e}")
        import traceback
        traceback.print_exc()
        try:
            status_queue.put("500")
        except Exception:
            pass
            return None
    finally:
        try:
            if page:
                await page.close()
        except Exception:
            pass
        try:
            if context:
                await context.close()
        except Exception:
            pass
        try:
            if browser:
                await browser.close()
        except Exception:
            pass


async def sohu_cookie_gen(id, status_queue):
    browser = None
    context = None
    page = None
    try:
        status_queue.put("MANUAL_LOGIN")
        print(f"🟢 开始搜狐号登录: id={id}")
        async with async_playwright() as playwright:
            options = get_browser_options()
            options['headless'] = False
            print(f"🟢 启动浏览器 options={ {k: v for k, v in options.items() if k != 'args'} }")
            browser = await playwright.chromium.launch(**options)
            # 搜狐后台为 qiankun 微前端，禁止注入 stealth（会破坏 createElement）
            context = await browser.new_context()
            page = await context.new_page()
            print("🟢 打开搜狐号登录页...")
            await page.goto("https://mp.sohu.com/mpfe/v4/login", timeout=60000, wait_until="domcontentloaded")
            print(f"🟢 登录页已打开: {page.url}")
            try:
                await page.wait_for_url(
                    lambda url: (
                        "mp.sohu.com" in str(url)
                        and "/login" not in str(url).lower()
                        and "passport.sohu.com" not in str(url).lower()
                    ),
                    timeout=200_000,
                )
                print("✅ 搜狐号登录成功，检测到进入创作者后台")
            except asyncio.TimeoutError:
                print("❌ 搜狐号登录超时")
                status_queue.put("500")
                return None

            uuid_v1 = uuid.uuid1()
            print(f"UUID v1: {uuid_v1}")
            cookies_dir = Path(BASE_DIR / "cookiesFile")
            cookies_dir.mkdir(exist_ok=True)
            await context.storage_state(path=cookies_dir / f"{uuid_v1}.json")

            result = await check_cookie(8, f"{uuid_v1}.json")
            if not result:
                print("⚠️ cookie 即时校验未通过，仍保存账号，请稍后刷新验证")

            with sqlite3.connect(Path(BASE_DIR / "db" / "database.db")) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO user_info (type, filePath, userName, status)
                    VALUES (?, ?, ?, ?)
                ''', (8, f"{uuid_v1}.json", id, 1 if result else 0))
                conn.commit()
                print("✅ 搜狐号用户状态已记录")
            status_queue.put("200")
            return True
    except Exception as e:
        print(f"❌ 搜狐号登录异常: {e}")
        import traceback
        traceback.print_exc()
        try:
            status_queue.put("500")
        except Exception:
            pass
        return None
    finally:
        try:
            if page:
                await page.close()
        except Exception:
            pass
        try:
            if context:
                await context.close()
        except Exception:
            pass
        try:
            if browser:
                await browser.close()
        except Exception:
            pass


async def zhihu_cookie_gen(id, status_queue):
    browser = None
    context = None
    page = None
    try:
        status_queue.put("MANUAL_LOGIN")
        print(f"🟢 开始知乎登录: id={id}")
        async with async_playwright() as playwright:
            options = get_browser_options()
            options['headless'] = False
            print(f"🟢 启动浏览器 options={ {k: v for k, v in options.items() if k != 'args'} }")
            browser = await playwright.chromium.launch(**options)
            context = await browser.new_context()
            context = await set_init_script(context)
            page = await context.new_page()
            print("🟢 打开知乎登录页...")
            await page.goto("https://www.zhihu.com/signin", timeout=60000, wait_until="domcontentloaded")
            print(f"🟢 登录页已打开: {page.url}")
            print("🟢 请在浏览器完成登录，等待登录凭证 z_c0…")
            from uploader.zhihu_uploader.main import _wait_until_logged_in
            ok = await _wait_until_logged_in(page, context, timeout_ms=200_000)
            if not ok:
                print("❌ 知乎登录超时：未检测到 z_c0")
                status_queue.put("500")
                return None
            print("✅ 知乎登录成功，已检测到 z_c0")

            uuid_v1 = uuid.uuid1()
            print(f"UUID v1: {uuid_v1}")
            cookies_dir = Path(BASE_DIR / "cookiesFile")
            cookies_dir.mkdir(exist_ok=True)
            await context.storage_state(path=cookies_dir / f"{uuid_v1}.json")

            result = await check_cookie(9, f"{uuid_v1}.json")
            if not result:
                print("⚠️ cookie 即时校验未通过，仍保存账号，请稍后刷新验证")

            with sqlite3.connect(Path(BASE_DIR / "db" / "database.db")) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO user_info (type, filePath, userName, status)
                    VALUES (?, ?, ?, ?)
                ''', (9, f"{uuid_v1}.json", id, 1 if result else 0))
                conn.commit()
                print("✅ 知乎用户状态已记录")
            status_queue.put("200")
            return True
    except Exception as e:
        print(f"❌ 知乎登录异常: {e}")
        import traceback
        traceback.print_exc()
        try:
            status_queue.put("500")
        except Exception:
            pass
        return None
    finally:
        try:
            if page:
                await page.close()
        except Exception:
            pass
        try:
            if context:
                await context.close()
        except Exception:
            pass
        try:
            if browser:
                await browser.close()
        except Exception:
            pass


# Bilibili登录（通过biliup CLI，在新终端窗口中扫码）
async def bilibili_cookie_gen(id, status_queue):
    import subprocess
    import sys
    from uploader.bilibili_uploader.runtime import ensure_biliup_binary

    account_dir = Path(BASE_DIR / "cookiesFile")
    account_dir.mkdir(exist_ok=True)
    account_file = account_dir / f"bilibili_{id}.json"

    # 获取正确的biliup二进制路径（不是pip安装的Python版）
    biliup_path = str(ensure_biliup_binary(force_check=False))

    # 通知前端已打开终端，请手动登录
    status_queue.put("MANUAL_LOGIN")

    try:
        # 在新终端窗口中运行 biliup login
        if sys.platform == 'win32':
            subprocess.Popen(
                [biliup_path, '-u', str(account_file), 'login'],
                creationflags=subprocess.CREATE_NEW_CONSOLE
            )
        else:
            subprocess.Popen(
                ['x-terminal-emulator', '-e', biliup_path, '-u', str(account_file), 'login']
            )
        print(f"✅ 已打开终端窗口，请在终端中扫码登录Bilibili")
    except Exception as e:
        print(f"❌ 打开终端失败: {e}")
        status_queue.put("500")
        return

    # 轮询等待cookie文件生成（用户在终端完成扫码后biliup会创建文件）
    for _ in range(100):  # 最多等200秒
        await asyncio.sleep(2)
        if account_file.exists():
            result = run_biliup_command(["-u", str(account_file), "renew"])
            if result.returncode == 0:
                print("✅ Bilibili登录成功")
                with sqlite3.connect(Path(BASE_DIR / "db" / "database.db")) as conn:
                    conn.cursor().execute(
                        'INSERT INTO user_info (type, filePath, userName, status) VALUES (?, ?, ?, ?)',
                        (6, f"bilibili_{id}.json", id, 1))
                    conn.commit()
                status_queue.put("200")
                return

    print("❌ Bilibili登录超时")
    status_queue.put("500")


# a = asyncio.run(xiaohongshu_cookie_gen(4,None))
# print(a)
