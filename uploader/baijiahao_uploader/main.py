# -*- coding: utf-8 -*-
import random
from datetime import datetime
from pathlib import Path

from playwright.async_api import Playwright, async_playwright, Page
import os
import time
import asyncio

from conf import LOCAL_CHROME_PATH, LOCAL_CHROME_HEADLESS
from utils.base_social_media import set_init_script
from utils.log import baijiahao_logger
from utils.network import async_retry


def _build_launch_kwargs(headless: bool) -> dict:
    options = {
        "headless": headless,
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--lang=zh-CN",
            "--disable-infobars",
            "--start-maximized",
        ],
    }
    if LOCAL_CHROME_PATH:
        options["executable_path"] = LOCAL_CHROME_PATH
    return options


async def _launch_browser(playwright: Playwright, headless: bool):
    launch_kwargs = _build_launch_kwargs(headless)
    try:
        return await playwright.chromium.launch(**launch_kwargs)
    except Exception:
        if "channel" not in launch_kwargs:
            launch_kwargs["channel"] = "chrome"
            return await playwright.chromium.launch(**launch_kwargs)
        raise


async def _install_preview_guard(page: Page) -> None:
    """预览模式下禁用发布按钮并显示提示，避免误点或页面热键触发发布。"""
    try:
        await page.evaluate(
            """() => {
                if (document.getElementById('sau-dry-run-banner')) return;
                const banner = document.createElement('div');
                banner.id = 'sau-dry-run-banner';
                banner.textContent = '⚠️ 仅预览模式：脚本不会点击发布，请勿手动点击「发布」按钮';
                banner.style.cssText = [
                    'position:fixed', 'top:0', 'left:0', 'right:0', 'z-index:2147483647',
                    'background:#e6a23c', 'color:#fff', 'padding:12px 16px', 'text-align:center',
                    'font-size:15px', 'font-weight:600', 'box-shadow:0 2px 8px rgba(0,0,0,.25)',
                ].join(';');
                document.body.appendChild(banner);

                const blockPublish = () => {
                    document.querySelectorAll('button, [role="button"], a').forEach((el) => {
                        const t = (el.innerText || el.textContent || '').trim();
                        if (!t || t.length > 12) return;
                        if (t === '发布' || t === '定时发布' || t.endsWith('发布')) {
                            el.setAttribute('data-sau-dry-run-blocked', '1');
                            el.style.pointerEvents = 'none';
                            el.style.opacity = '0.45';
                            if ('disabled' in el) el.disabled = true;
                        }
                    });
                };
                blockPublish();
                if (!window.__sauDryRunObserver) {
                    window.__sauDryRunObserver = new MutationObserver(blockPublish);
                    window.__sauDryRunObserver.observe(document.documentElement, {
                        childList: true, subtree: true,
                    });
                }
            }"""
        )
    except Exception as exc:
        baijiahao_logger.debug(f"预览保护注入失败: {exc}")


async def _dismiss_overlays(page: Page) -> None:
    for selector in (
        'button:has-text("我知道了")',
        'button:has-text("知道了")',
        'button:has-text("关闭")',
    ):
        try:
            btn = page.locator(selector).first
            if await btn.count() and await btn.is_visible():
                await btn.click(timeout=1000)
                await page.wait_for_timeout(300)
        except Exception:
            continue


async def baijiahao_cookie_gen(account_file):
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
        await page.goto("https://baijiahao.baidu.com/builder/theme/bjh/login")
        await page.pause()
        # 点击调试器的继续，保存cookie
        await context.storage_state(path=account_file)
        baijiahao_logger.success("cookie saved")


async def cookie_auth(account_file):
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=LOCAL_CHROME_HEADLESS)
        context = await browser.new_context(storage_state=account_file)
        context = await set_init_script(context)
        # 创建一个新的页面
        page = await context.new_page()
        # 访问指定的 URL
        await page.goto("https://baijiahao.baidu.com/builder/rc/home")
        await page.wait_for_timeout(timeout=5000)

        if await page.get_by_text('注册/登录百家号').count():
            baijiahao_logger.error("等待5秒 cookie 失效")
            return False
        else:
            baijiahao_logger.success("[+] cookie 有效")
            return True


async def baijiahao_setup(account_file, handle=False):
    if not os.path.exists(account_file) or not await cookie_auth(account_file):
        if not handle:
            return False
        baijiahao_logger.error("cookie文件不存在或已失效，即将自动打开浏览器，请扫码登录，登陆后会自动生成cookie文件")
        await baijiahao_cookie_gen(account_file)
    return True

class BaiJiaHaoVideo(object):
    def __init__(self, title, file_path, tags, publish_date: datetime, account_file, proxy_setting=None):
        self.title = title  # 视频标题
        self.file_path = file_path
        self.tags = tags
        self.publish_date = publish_date
        self.account_file = account_file
        self.date_format = '%Y年%m月%d日 %H:%M'
        self.local_executable_path = LOCAL_CHROME_PATH
        self.headless = LOCAL_CHROME_HEADLESS
        self.proxy_setting = proxy_setting

    async def set_schedule_time(self, page, publish_date):
        """
        todo 时间选择，日后在处理 百家号的时间选择不准确，目前是随机
        """
        publish_date_day = f"{publish_date.month}月{publish_date.day}日" if publish_date.day >9  else f"{publish_date.month}月0{publish_date.day}日"
        publish_date_hour = f"{publish_date.hour}点"
        publish_date_min = f"{publish_date.minute}分"
        await page.wait_for_selector('div.select-wrap', timeout=5000)
        for _ in range(3):
            try:
                await page.locator('div.select-wrap').nth(0).click()
                await page.wait_for_selector('div.rc-virtual-list  div.cheetah-select-item', timeout=5000)
                break
            except:
                await page.locator('div.select-wrap').nth(0).click()
        # page.locator(f'div.rc-virtual-list-holder-inner >> text={publish_date_day}').click()
        await page.wait_for_timeout(2000)
        await page.locator(f'div.rc-virtual-list  div.cheetah-select-item >> text={publish_date_day}').click()
        await page.wait_for_timeout(2000)

        # 改为随机点击一个 hour
        for _ in range(3):
            try:
                await page.locator('div.select-wrap').nth(1).click()
                await page.wait_for_selector('div.rc-virtual-list div.rc-virtual-list-holder-inner:visible', timeout=5000)
                break
            except:
                await page.locator('div.select-wrap').nth(1).click()
        await page.wait_for_timeout(2000)
        current_choice_hour = await page.locator('div.rc-virtual-list:visible div.cheetah-select-item-option').count()
        await page.wait_for_timeout(2000)
        await page.locator('div.rc-virtual-list:visible div.cheetah-select-item-option').nth(
            random.randint(1, current_choice_hour-3)).click()
        # 2024.08.05 current_choice_hour的获取可能有问题，页面有7，这里获取了10，暂时硬编码至6

        await page.wait_for_timeout(2000)
        await page.locator("button >> text=定时发布").click()


    async def handle_upload_error(self, page):
        # 日后实现，目前没遇到
        return
        print("视频出错了，重新上传中")

    async def upload(self, playwright: Playwright) -> None:
        # 使用 Chromium 浏览器启动一个浏览器实例
        browser = await playwright.chromium.launch(headless=self.headless, executable_path=self.local_executable_path, proxy=self.proxy_setting)
        # 创建一个浏览器上下文，使用指定的 cookie 文件
        context = await browser.new_context(storage_state=f"{self.account_file}", user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.4324.150 Safari/537.36')
        # context = await set_init_script(context)
        await context.grant_permissions(['geolocation'])

        # 创建一个新的页面
        page = await context.new_page()
        # 访问指定的 URL
        await page.goto("https://baijiahao.baidu.com/builder/rc/edit?type=videoV2", timeout=60000)
        baijiahao_logger.info(f"正在上传-------{self.title}.mp4")
        # 等待页面跳转到指定的 URL，没进入，则自动等待到超时
        baijiahao_logger.info('正在打开主页...')
        await page.wait_for_url("https://baijiahao.baidu.com/builder/rc/edit?type=videoV2", timeout=60000)

        # 点击 "上传视频" 按钮
        await page.locator("div[class^='video-main-container'] input").set_input_files(self.file_path)

        # 等待页面跳转到指定的 URL
        while True:
            # 判断是是否进入视频发布页面，没进入，则自动等待到超时
            try:
                await page.wait_for_selector("div#formMain:visible")
                break
            except:
                baijiahao_logger.info("正在等待进入视频发布页面...")
                await asyncio.sleep(0.1)

        # 填充标题和话题
        # 这里为了避免页面变化，故使用相对位置定位：作品标题父级右侧第一个元素的input子元素
        await asyncio.sleep(1)
        baijiahao_logger.info("正在填充标题和话题...")
        await self.add_title_tags(page)

        upload_status = await self.uploading_video(page)
        if not upload_status:
            baijiahao_logger.error(f"发现上传出错了... 文件:{self.file_path}")
            raise

        # 判断视频封面图是否生成成功
        while True:
            baijiahao_logger.info("正在确认封面完成, 准备去点击定时/发布...")
            if await page.locator("div.cheetah-spin-container img").count():
                baijiahao_logger.info("封面已完成，点击定时/发布...")
                break
            else:
                baijiahao_logger.info("等待封面生成...")
                await asyncio.sleep(3)

        await self.publish_video(page, self.publish_date)
        await page.wait_for_timeout(2000)
        if await page.locator('div.passMod_dialog-container >> text=百度安全验证:visible').count():
            baijiahao_logger.error("出现验证，退出")
            raise Exception("出现验证，退出")
        await page.wait_for_url("https://baijiahao.baidu.com/builder/rc/clue**", timeout=5000)
        baijiahao_logger.success("视频发布成功")

        await context.storage_state(path=self.account_file)  # 保存cookie
        baijiahao_logger.info('cookie更新完毕！')
        await asyncio.sleep(2)  # 这里延迟是为了方便眼睛直观的观看
        # 关闭浏览器上下文和浏览器实例
        await context.close()
        await browser.close()


    @async_retry(timeout=300)  # 例如，最多重试3次，超时时间为180秒
    async def uploading_video(self, page):
        while True:
            upload_failed = await page.locator('div .cover-overlay:has-text("上传失败")').count()
            if upload_failed:
                baijiahao_logger.error("发现上传出错了...")
                # await self.handle_upload_error(page)  # 假设这是处理上传错误的函数
                return False

            uploading = await page.locator('div .cover-overlay:has-text("上传中")').count()
            if uploading:
                baijiahao_logger.info("正在上传视频中...")
                await asyncio.sleep(2)  # 等待2秒再次检查
                continue

            # 检查上传是否成功
            if not uploading and not upload_failed:
                baijiahao_logger.success("视频上传完毕")
                return True

    async def set_schedule_publish(self, page, publish_date):
        while True:
            schedule_element = page.locator("div.op-btn-outter-content >> text=定时发布").locator("..").locator(
                'button')
            try:
                await schedule_element.click()
                await page.wait_for_selector('div.select-wrap:visible', timeout=3000)
                await page.wait_for_timeout(timeout=2000)
                baijiahao_logger.info("开始点击发布定时...")
                await self.set_schedule_time(page, publish_date)
                break
            except Exception as e:
                baijiahao_logger.error(f"定时发布失败: {e}")
                raise  # 重新抛出异常，让重试装饰器捕获

    @async_retry(timeout=300)  # 例如，最多重试3次，超时时间为180秒
    async def publish_video(self, page: Page, publish_date):
        if publish_date != 0:
            # 定时发布
            await self.set_schedule_publish(page, publish_date)
        else:
            # 立即发布
            await self.direct_publish(page)

    async def direct_publish(self, page):
        try:
            publish_button = page.locator("button >> text=发布")
            if await publish_button.count():
                await publish_button.click()
        except Exception as e:
            baijiahao_logger.error(f"直接发布视频失败: {e}")
            raise  # 重新抛出异常，让重试装饰器捕获

    async def add_title_tags(self, page):
        title_container = page.get_by_placeholder('添加标题获得更多推荐')
        if len(self.title) <= 8:
            self.title += " 你不知道的"
        await title_container.fill(self.title[:30])

    async def main(self):
        async with async_playwright() as playwright:
            await self.upload(playwright)



    # 使用 AI成片 功能
    async def ai2video(self, playwright: Playwright) -> None:
        # 使用 Chromium 浏览器启动一个浏览器实例
        browser = await playwright.chromium.launch(headless=self.headless, executable_path=self.local_executable_path, proxy=self.proxy_setting)
        # 创建一个浏览器上下文，使用指定的 cookie 文件
        context = await browser.new_context(
            viewport={"width": 1600, "height": 900},
            storage_state=f"{self.account_file}",
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.4324.150 Safari/537.36'
        )
        # context = await set_init_script(context)
        await context.grant_permissions(['geolocation'])

        # 创建一个新的页面
        page = await context.new_page()
        # 访问指定的 URL
        await page.goto("https://aigc.baidu.com/make", timeout=60000)
        # 等待页面跳转到指定的 URL，没进入，则自动等待到超时
        baijiahao_logger.info('正在打开主页...')
        await page.wait_for_url("https://aigc.baidu.com/make", timeout=60000)

        # 点击"全网"标签
        await page.locator('div.rounded-lg.border:has-text("全网")').click()
        await asyncio.sleep(1)  # 这里延迟是为了方便眼睛直观的观看

        # 点击 "上传视频" 按钮
        # await page.locator("div[class^='video-main-container'] input").set_input_files(self.file_path)

        # region 操作处

        # 生成日期时间键名（格式：ai2video_YYYYMMDDHHMM）
        now = datetime.now()
        datetime_str = now.strftime("%Y%m%d%H%M")
        processed_key = "ai2video_processed_titles"
        batch_key = f"ai2video_{datetime_str}"

        # 初始化LocalStorage
        await page.evaluate(f"""
                   if (!localStorage.getItem("{processed_key}")) {{
                       localStorage.setItem("{processed_key}", JSON.stringify([]));                   
                   }}
                   if (!localStorage.getItem("{batch_key}")) {{
                       localStorage.setItem("{batch_key}", JSON.stringify([]));                   
                   }}
               """)

        # 定位新闻列表容器（转义特殊CSS字符）
        container_selector = '.overflow-auto.flex-grow.h-0.saas-scrollbar.mt\-\[-4px\].pl\-\[24px\].pr\-\[10px\].pb\-\[18px\]'
        news_items = await page.locator(container_selector).locator('div.py\-\[6px\].group.cursor-pointer').all()

        for item in news_items:
            try:
                # 获取新闻标题
                title_elem = item.locator('div.flex.text-gray-darker.items-center.relative.pr\-\[56px\] > span')
                title = await title_elem.text_content()
                if not title:
                    continue

                # 检查是否已处理过
                is_processed = await page.evaluate(
                    f"""title => {{
                               const processedList = JSON.parse(localStorage.getItem("{processed_key}") || "[]");
                               return processedList.includes(title);
                           }}""",
                    title
                )

                if is_processed:
                    print(f"[跳过] {title}")
                    continue

                # 悬停显示按钮（根据HTML结构，按钮在悬停时显示）
                await item.hover()

                # 点击生成文案按钮
                button = item.locator('button:has-text("生成文案")')
                await button.click()
                print(f"[点击] {title}")

                # 等待30秒
                # await page.wait_for_timeout(30000)
                print(f"[等待完成] {title}")
                
                # 监听"一键成片"按钮
                print(f"[开始监听] 一键成片按钮")
                should_exit_while_loop = False  # 添加标志变量
                while True:
                    # 定位"一键成片"按钮
                    one_key_button = page.locator("button:has-text('一键成片')")
                    
                    # 检查按钮是否存在
                    if await one_key_button.count() > 0:
                        # 检查按钮是否有disabled属性
                        is_disabled = await one_key_button.get_attribute("disabled")
                        
                        if is_disabled is None:
                            # 按钮不再被禁用，点击它
                            print(f"[发现可点击按钮] 一键成片")
                            await one_key_button.click()  # 先点击一键成片按钮
                            
                            # 等待可能出现的"温馨提示"窗口
                            print(f"[检查] 是否出现温馨提示窗口")
                            await page.wait_for_timeout(2000)  # 等待2秒，让窗口有时间显示
                            
                            try:
                                # 检查是否存在"温馨提示"窗口，设置较短的超时时间
                                tip_window = page.locator("div:has-text('温馨提示') >> visible=true")
                                if await tip_window.count() > 0:
                                    print(f"[发现] 温馨提示窗口")
                                    
                                    # 定位并点击"知道了"按钮，设置较短的超时时间
                                    know_button = page.locator("button:has-text('知道了')")
                                    if await know_button.count() > 0:
                                        try:
                                            # 设置较短的超时时间进行点击
                                            await know_button.click(timeout=5000)
                                            print(f"[已点击] 知道了按钮")
                                        except Exception as e:
                                            print(f"[警告] 点击知道了按钮时出错: {str(e)}")
                                    else:
                                        print(f"[警告] 未找到知道了按钮")
                                else:
                                    print(f"[信息] 未出现温馨提示窗口，继续执行")
                            except Exception as e:
                                print(f"[警告] 处理温馨提示窗口时出错: {str(e)}")
                                # 继续执行，不要因为这个错误中断流程
                                
                            # 记录到LocalStorage前打印日志
                            print(f"[开始记录] 准备将标题 '{title}' 记录到LocalStorage")
                            
                            # 记录到LocalStorage
                            await page.evaluate(
                                f"""
                                        (title, processedKey, batchKey) => {{
                                            // 更新已处理列表
                                            const processedList = JSON.parse(localStorage.getItem(processedKey) || "[]");
                                            if (!processedList.includes(title)) {{
                                                processedList.push(title);
                                                localStorage.setItem(processedKey, JSON.stringify(processedList));
                                            }}

                                            // 更新当前批次记录
                                            const batchList = JSON.parse(localStorage.getItem(batchKey) || "[]");
                                            if (!batchList.includes(title)) {{
                                                batchList.push(title);
                                                localStorage.setItem(batchKey, JSON.stringify(batchList));
                                            }}
                                        }}
                                        """,
                                title, processed_key, batch_key
                            )
                            
                            # 记录完成后打印日志
                            print(f"[记录完成] 标题 '{title}' 已成功记录到LocalStorage")

                            print(f"[记录完成] {title}")
                            
                            # 监听新打开的标签页
                            print(f"[监听] 等待新标签页打开")
                            # 获取当前所有页面
                            current_pages = context.pages
                            current_page_count = len(current_pages)
                            
                            # 等待新标签页打开（最多等待10秒）
                            new_page = None
                            max_wait_time = 10  # 最大等待时间（秒）
                            start_time = time.time()
                            
                            while time.time() - start_time < max_wait_time:
                                # 获取最新的页面列表
                                pages = context.pages
                                # 如果页面数量增加，说明新标签页已打开
                                if len(pages) > current_page_count:
                                    # 获取最新打开的页面（通常是列表中的最后一个）
                                    new_page = pages[-1]
                                    print(f"[发现] 新标签页已打开")
                                    break
                                # 短暂等待后再次检查
                                await asyncio.sleep(0.5)
                            
                            # 如果找到新标签页，获取其标题和URL并保存
                            if new_page:
                                # 等待页面加载完成
                                try:
                                    await new_page.wait_for_load_state("domcontentloaded", timeout=5000)
                                    # 获取页面标题和URL
                                    page_title = await new_page.title()
                                    page_url = new_page.url
                                    
                                    print(f"[获取] 标题: {page_title}")
                                    print(f"[获取] URL: {page_url}")
                                    
                                    # 将标题和URL保存到url.txt文件
                                    with open("url.txt", "a", encoding="utf-8") as f:
                                        f.write(f"{page_title}\n{page_url}\n\n")
                                    
                                    print(f"[保存] 标题和URL已保存到url.txt")
                                    
                                    # 等待5秒后关闭新标签页
                                    print(f"[等待] 5秒后将关闭新标签页")
                                    await asyncio.sleep(5)
                                    await new_page.close()
                                    print(f"[关闭] 新标签页已关闭")
                                except Exception as e:
                                    print(f"[错误] 处理新标签页时出错: {str(e)}")
                                    try:
                                        # 尝试关闭页面，即使出错
                                        await new_page.close()
                                        print(f"[关闭] 新标签页已关闭（出错后）")
                                    except:
                                        pass
                            else:
                                print(f"[警告] 未检测到新标签页打开")
                            
                            # 跳出整个while循环
                            print(f"[操作] 跳出所有循环，不再处理其他新闻")
                            should_exit_while_loop = True  # 设置标志变量
                            break  # 跳出while循环
                    
                    # 检查是否需要跳出while循环
                    if should_exit_while_loop:
                        break
                        
                    # 每秒检查一次按钮状态
                    await page.wait_for_timeout(1000)
                
                # 检查是否需要跳出for循环
                if should_exit_while_loop:
                    print(f"[操作] 跳出for循环，完全结束处理")
                    break  # 跳出for循环
            except Exception as e:
                print(f"处理新闻时出错: {str(e)}")
                continue


        # endregion 操作处

        print(f"[循环完成] 准备关闭浏览器")

        # 暂停 1000s
        await asyncio.sleep(1000)  # 这里延迟是为了方便眼睛直观的观看

        # 退出前保存 storage 信息
        await context.storage_state(path=self.account_file)  # 保存cookie
        baijiahao_logger.info('cookie更新完毕！')
        await asyncio.sleep(2)  # 这里延迟是为了方便眼睛直观的观看
        # 关闭浏览器上下文和浏览器实例
        await context.close()
        await browser.close()


    async def mainAi(self):
        async with async_playwright() as playwright:
            await self.ai2video(playwright)


BAIJIAHAO_ARTICLE_URLS = [
    "https://baijiahao.baidu.com/builder/rc/edit?type=news&is_from_cms=1",
    "https://baijiahao.baidu.com/builder/rc/edit?type=news",
]


class BaiJiaHaoArticle(object):
    """百家号图文文章发布（type=news，非视频、非动态）。"""

    def __init__(
        self,
        title,
        body,
        tags,
        publish_date: datetime | int,
        account_file,
        dry_run=False,
        cover_path=None,
        ai_generated=False,
    ):
        self.title = (title or "")[:64]
        self.body = body or ""
        self.tags = tags or []
        self.publish_date = publish_date
        self.account_file = str(account_file)
        self.headless = LOCAL_CHROME_HEADLESS if not dry_run else False
        self.dry_run = bool(dry_run)
        self.cover_path = cover_path
        self.ai_generated = bool(ai_generated)

    def _normalize_tags(self) -> list[str]:
        tags = [str(t).strip().lstrip("#") for t in (self.tags or []) if str(t).strip()]
        seen = set()
        normalized = []
        for tag in tags:
            if tag in seen:
                continue
            seen.add(tag)
            normalized.append(tag)
        return normalized[:5]

    def _compose_body(self) -> str:
        return (self.body or "").strip()

    async def _is_article_page_ready(self, page: Page) -> bool:
        title_selectors = [
            "div.input-box textarea",
            'div.input-box [contenteditable="true"]',
            'input[placeholder*="标题"]',
            'textarea[placeholder*="标题"]',
        ]
        title_ready = False
        for sel in title_selectors:
            try:
                if await page.locator(sel).count():
                    title_ready = True
                    break
            except Exception:
                continue
        if not title_ready:
            return False
        return await self._find_body_editor(page) is not None

    async def _wait_for_body_editor(self, page: Page, timeout_ms: int = 20000):
        for _ in range(max(1, timeout_ms // 500)):
            editor = await self._find_body_editor(page)
            if editor:
                return editor
            await page.wait_for_timeout(500)
        return None

    async def _fill_hidden_title_textarea(self, page: Page, title_text: str) -> bool:
        try:
            return bool(
                await page.evaluate(
                    """(title) => {
                        const textarea = document.querySelector('div.input-box textarea');
                        if (!textarea) return false;
                        textarea.value = title;
                        textarea.dispatchEvent(new Event('input', { bubbles: true }));
                        textarea.dispatchEvent(new Event('change', { bubbles: true }));
                        return !!textarea.value;
                    }""",
                    title_text,
                )
            )
        except Exception:
            return False

    async def fill_title(self, page: Page) -> None:
        baijiahao_logger.info("开始查找文章标题输入框...")
        title_text = self.title or "未命名文章"
        candidates = [
            page.locator('div.input-box [contenteditable="true"]').first,
            page.get_by_placeholder("请输入标题（2 - 64字）"),
            page.locator('input[placeholder*="标题"]').first,
            page.locator('textarea[placeholder*="标题"]').first,
            page.locator('input[placeholder*="请输入"]').first,
            page.locator('input[name*="title"]').first,
            page.get_by_placeholder("请输入标题").first,
            page.get_by_placeholder("请输入文章标题").first,
        ]

        for loc in candidates:
            try:
                if not await loc.count() or not await loc.is_visible():
                    continue
                await loc.click(force=True)
                await page.wait_for_timeout(200)
                try:
                    await loc.fill("")
                    await loc.fill(title_text)
                except Exception:
                    await page.keyboard.press("Control+A")
                    await page.keyboard.press("Backspace")
                    await page.keyboard.type(title_text)
                baijiahao_logger.info(f"已填写文章标题: {title_text}")
                await page.keyboard.press("Escape")
                await page.wait_for_timeout(150)
                return
            except Exception:
                continue

        if await self._fill_hidden_title_textarea(page, title_text):
            baijiahao_logger.info(f"已通过隐藏 textarea 填写标题: {title_text}")
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(150)
            return

        raise RuntimeError("未找到百家号文章标题输入框")

    async def _blur_title_editor(self, page: Page) -> None:
        try:
            await page.evaluate(
                """() => {
                    const title = document.querySelector('div.input-box [contenteditable="true"]');
                    if (title) title.blur();
                    const active = document.activeElement;
                    if (active && active.closest && active.closest('div.input-box')) {
                        active.blur();
                    }
                }"""
            )
            await page.wait_for_timeout(100)
        except Exception:
            pass

    async def _focus_body_editor(self, page: Page, editor) -> None:
        try:
            await self._blur_title_editor(page)
            await editor.scroll_into_view_if_needed()
            await editor.click(force=True)
            await page.wait_for_timeout(200)
            await editor.evaluate(
                """(el) => {
                    el.focus();
                    const sel = window.getSelection();
                    const range = document.createRange();
                    range.selectNodeContents(el);
                    range.collapse(false);
                    sel.removeAllRanges();
                    sel.addRange(range);
                }"""
            )
            await page.wait_for_timeout(150)
            in_body = await editor.evaluate(
                """(el) => {
                    const active = document.activeElement;
                    return active === el || el.contains(active);
                }"""
            )
            if not in_body:
                box = await editor.bounding_box()
                if box:
                    await page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                    await page.wait_for_timeout(150)
        except Exception:
            pass

    async def _get_body_editable(self, page: Page, editor):
        try:
            is_editable = await editor.evaluate(
                """(el) => !!(el.isContentEditable || el.getAttribute('contenteditable') === 'true')"""
            )
            if is_editable:
                return editor
        except Exception:
            pass
        try:
            inner = editor.locator('[contenteditable="true"]').first
            if await inner.count() and await inner.is_visible():
                return inner
        except Exception:
            pass
        for sel in (
            '.news-editor-pc [contenteditable="true"]',
            'div.edui-editor [contenteditable="true"]',
            'div[class*="editor"] [contenteditable="true"]:not(div.input-box [contenteditable="true"])',
        ):
            loc = page.locator(sel).first
            try:
                if await loc.count() and await loc.is_visible():
                    in_title = await loc.evaluate("el => !!el.closest('div.input-box')")
                    if not in_title:
                        return loc
            except Exception:
                continue
        return editor

    async def _find_body_editor(self, page: Page):
        body_selectors = [
            '.news-editor-pc [contenteditable="true"]',
            ".news-editor-pc",
            'div.edui-editor [contenteditable="true"]',
            'div[class*="editor"] [contenteditable="true"]',
        ]

        for frame in page.frames:
            if frame == page.main_frame:
                continue
            for sel in body_selectors:
                try:
                    loc = frame.locator(sel).first
                    if await loc.count():
                        if sel.endswith('[contenteditable="true"]') or await loc.is_visible():
                            return loc
                except Exception:
                    continue

        for sel in body_selectors:
            loc = page.locator(sel).first
            try:
                if await loc.count() and await loc.is_visible():
                    in_title = await loc.evaluate("el => !!el.closest('div.input-box')")
                    if not in_title:
                        if sel == ".news-editor-pc":
                            inner = loc.locator('[contenteditable="true"]').first
                            if await inner.count():
                                return inner
                        if not sel.endswith('[contenteditable="true"]'):
                            inner = loc.locator('[contenteditable="true"]').first
                            if await inner.count():
                                return inner
                        return loc
            except Exception:
                continue

        for sel in ('[contenteditable="true"]', 'div[role="textbox"]', ".ProseMirror", ".ql-editor"):
            loc = page.locator(sel).first
            try:
                if await loc.count() and await loc.is_visible():
                    in_title = await loc.evaluate("el => !!el.closest('div.input-box')")
                    if not in_title:
                        return loc
            except Exception:
                continue
        return None

    async def _find_editor(self, page: Page):
        return await self._find_body_editor(page)

    async def fill_body(self, page: Page) -> None:
        editor = await self._wait_for_body_editor(page)
        if not editor:
            raise RuntimeError("未找到百家号文章正文编辑区")

        text = self._compose_body()
        if not text.strip():
            raise ValueError("文章正文不能为空")

        filled = False
        try:
            await page.context.grant_permissions(["clipboard-read", "clipboard-write"])
        except Exception:
            pass
        await self._focus_body_editor(page, editor)
        try:
            await page.keyboard.press("Control+A")
            await page.keyboard.press("Backspace")
            await page.evaluate(
                """async (t) => { await navigator.clipboard.writeText(t); }""",
                text,
            )
            await page.keyboard.press("Control+V")
            await page.wait_for_timeout(800)
            filled = True
            baijiahao_logger.info("文章正文已通过剪贴板粘贴")
        except Exception as exc:
            baijiahao_logger.warning(f"剪贴板粘贴正文失败: {exc}")

        if not filled:
            await self._focus_body_editor(page, editor)
            try:
                await editor.fill(text)
            except Exception:
                await editor.evaluate(
                    """(el, t) => {
                        el.focus();
                        el.innerText = t;
                        el.dispatchEvent(new InputEvent('input', { bubbles: true, data: t }));
                    }""",
                    text,
                )
            baijiahao_logger.info("文章正文已通过 fill/DOM 写入")

        await self.insert_topics_in_body(page, editor)

    async def _move_caret_to_editor_end(self, page: Page, editor) -> None:
        try:
            await self._blur_title_editor(page)
            await editor.click(force=True)
        except Exception:
            pass
        await page.wait_for_timeout(100)
        for key in ("Control+End", "End", "Control+ArrowDown"):
            try:
                await page.keyboard.press(key)
            except Exception:
                pass
        try:
            await editor.evaluate(
                """(el) => {
                    el.focus();
                    const sel = window.getSelection();
                    const range = document.createRange();
                    const topics = el.querySelectorAll('a[data-bjh-box="topic"]');
                    if (topics.length) {
                        const last = topics[topics.length - 1];
                        range.setStartAfter(last);
                        range.collapse(true);
                    } else {
                        range.selectNodeContents(el);
                        range.collapse(false);
                    }
                    sel.removeAllRanges();
                    sel.addRange(range);
                }"""
            )
        except Exception:
            pass
        await page.wait_for_timeout(150)

    async def _mouse_click_xy(self, page: Page, x: float, y: float) -> None:
        await page.mouse.move(float(x), float(y), steps=8)
        await page.wait_for_timeout(120)
        await page.mouse.down()
        await page.wait_for_timeout(50)
        await page.mouse.up()
        await page.wait_for_timeout(350)

    def _normalize_topic_label(self, text: str) -> str:
        return (text or "").strip().strip("#").strip()

    def _longest_common_substring(self, a: str, b: str) -> str:
        best = ""
        for i in range(len(a)):
            for j in range(i + 1, len(a) + 1):
                sub = a[i:j]
                if len(sub) > len(best) and sub in b:
                    best = sub
        return best

    def _score_topic_match(self, tag: str, topic_text: str) -> int:
        if not tag or not topic_text:
            return 0
        if topic_text == tag:
            return 1000
        if len(tag) >= 2 and len(topic_text) >= 2:
            if tag in topic_text:
                return 850 + len(tag) * 5
            if topic_text in tag:
                return 800 + len(topic_text) * 5

        prefix_len = 0
        for i in range(min(len(tag), len(topic_text)), 0, -1):
            if tag[:i] == topic_text[:i]:
                prefix_len = i
                break
        if prefix_len >= 2:
            return 600 + prefix_len * 50

        suffix_len = 0
        for i in range(min(len(tag), len(topic_text)), 0, -1):
            if tag[-i:] == topic_text[-i:]:
                suffix_len = i
                break
        if suffix_len >= 2:
            score = 480 + suffix_len * 30
            if len(topic_text) <= len(tag) + 4:
                return score
            return 0

        for size in range(min(len(tag), 4), 1, -1):
            part = tag[:size]
            if topic_text.endswith(part) and len(topic_text) <= len(tag) + 6:
                return 460 + size * 25

        best_sub = self._longest_common_substring(tag, topic_text)
        if len(best_sub) >= 3:
            score = 430 + len(best_sub) * 25
            if len(topic_text) > len(tag) + 6:
                score -= 180
            return max(score, 0)

        if len(best_sub) >= 2 and (
            (tag.startswith(best_sub) and topic_text.startswith(best_sub))
            or (tag.endswith(best_sub) and topic_text.endswith(best_sub))
        ):
            score = 410 + len(best_sub) * 20
            if len(topic_text) > len(tag) + 6:
                score -= 180
            return max(score, 0)

        return 0

    MIN_TOPIC_MATCH_SCORE = 400

    async def _find_topic_dropdown_candidates(self, page: Page, tag: str) -> list[dict]:
        try:
            items = await page.evaluate(
                """(tag) => {
                    const needle = String(tag || '').trim();
                    const isVis = (el) => {
                        const r = el.getBoundingClientRect();
                        const s = window.getComputedStyle(el);
                        return r.width >= 20 && r.height >= 14
                            && s.visibility !== 'hidden'
                            && s.display !== 'none'
                            && Number(s.opacity || 1) > 0.05
                            && r.bottom > 0 && r.top < (window.innerHeight + 20);
                    };
                    const pushRow = (el, baseScore) => {
                        if (!isVis(el)) return null;
                        const textEl = el.querySelector('.topic-text');
                        const raw = ((textEl && textEl.innerText) || el.innerText || el.textContent || '')
                            .replace(/\\s+/g, ' ').trim();
                        if (!raw || raw.length > 50) return null;
                        const r = el.getBoundingClientRect();
                        let score = baseScore;
                        if (needle && (raw.includes(needle) || raw.includes('#' + needle))) score += 25;
                        if (raw.includes('#')) score += 5;
                        if (el.closest('.topic-list, .topic-item-wrap')) score += 15;
                        if (el.classList && el.classList.contains('topic-item')) score += 10;
                        return {
                            text: raw,
                            topic_text: raw.replace(/^#+|#+$/g, '').trim(),
                            x: r.left + r.width / 2,
                            y: r.top + r.height / 2,
                            score,
                        };
                    };
                    const rows = [];
                    document.querySelectorAll('.topic-list .topic-item, .topic-item-wrap .topic-item').forEach(el => {
                        const row = pushRow(el, 20);
                        if (row) rows.push(row);
                    });
                    if (rows.length) return rows;

                    const all = Array.from(document.querySelectorAll('body *'));
                    const layers = all.filter(el => {
                        if (!isVis(el)) return false;
                        const s = window.getComputedStyle(el);
                        const cls = String(el.className || '');
                        return (s.position === 'fixed' || s.position === 'absolute'
                            || /topic-list|topic-item|mention|suggest|dropdown|popover|popup|panel|select|hashtag|at-list|tag/i.test(cls))
                            && el.getBoundingClientRect().height >= 30;
                    });
                    for (const layer of layers.slice(0, 8)) {
                        layer.querySelectorAll('.topic-item, li, [role=\"option\"], div, span, a').forEach(el => {
                            const row = pushRow(el, 8);
                            if (row) rows.push(row);
                        });
                    }
                    const uniq = [];
                    for (const it of rows.sort((a, b) => b.score - a.score)) {
                        if (uniq.some(u => u.text === it.text && Math.abs(u.x - it.x) < 8 && Math.abs(u.y - it.y) < 8)) {
                            continue;
                        }
                        uniq.push(it);
                    }
                    return uniq.slice(0, 30);
                }""",
                tag or "",
            )
            return items or []
        except Exception as exc:
            baijiahao_logger.debug(f"收集话题下拉失败: {exc}")
            return []

    def _is_real_bjh_topic_dropdown_item(self, text: str, tag: str = "") -> bool:
        t = (text or "").replace("\n", " ").strip()
        if not t or len(t) > 50:
            return False
        junk = (
            "发布", "定时", "封面", "上传", "取消", "确定", "保存", "预览",
            "默认分类", "默认#", "图文", "视频", "动态", "直播", "合集", "图集",
            "AI成片", "规则中心", "问题咨询", "收起",
        )
        if any(k in t for k in junk):
            return False
        if len(t) > 20 and sum(1 for k in ("图文", "视频", "动态", "直播") if k in t) >= 2:
            return False
        label = self._normalize_topic_label(t)
        tag = (tag or "").strip().lstrip("#")
        if not label:
            return False
        if tag and len(tag) > 2 and len(label) == 1:
            return False
        if "#" in t or t.startswith("#"):
            return True
        return bool(tag and tag in label)

    def _rank_topic_candidates(self, candidates: list[dict], tag: str) -> list[dict]:
        tag = (tag or "").strip().lstrip("#")
        ranked = []
        for c in candidates or []:
            text = str(c.get("text") or "")
            topic_text = str(c.get("topic_text") or self._normalize_topic_label(text))
            if not self._is_real_bjh_topic_dropdown_item(text, tag):
                continue
            match_score = self._score_topic_match(tag, topic_text)
            if len(topic_text) == 1 and len(tag) > 2:
                match_score -= 400
            if match_score < self.MIN_TOPIC_MATCH_SCORE:
                continue
            ranked.append({**c, "topic_text": topic_text, "score": int(c.get("score") or 0) + match_score})
        ranked.sort(key=lambda x: x.get("score", 0), reverse=True)
        return ranked

    async def _count_confirmed_topics(self, editor) -> int:
        try:
            return int(
                await editor.evaluate(
                    """(el) => el.querySelectorAll('a[data-bjh-box=\"topic\"]').length"""
                )
            )
        except Exception:
            return 0

    async def _editor_contains_confirmed_topic(self, editor, tag: str) -> bool:
        tag = (tag or "").strip().lstrip("#")
        if not tag:
            return False
        try:
            return bool(
                await editor.evaluate(
                    """(el, tag) => {
                        const nodes = el.querySelectorAll('a[data-bjh-box=\"topic\"]');
                        for (const node of nodes) {
                            const t = (node.innerText || node.textContent || '')
                                .trim().replace(/^#+|#+$/g, '');
                            if (t === tag || t.includes(tag) || tag.includes(t)) return true;
                        }
                        return false;
                    }""",
                    tag,
                )
            )
        except Exception:
            return False

    async def _topic_click_succeeded(self, editor, tag: str, before_nodes: int | None) -> bool:
        if await self._editor_contains_confirmed_topic(editor, tag):
            return True
        if before_nodes is not None:
            after_nodes = await self._count_confirmed_topics(editor)
            if after_nodes > before_nodes:
                return True
        return False

    async def _wait_for_topic_dropdown(self, page: Page, tag: str, timeout_ms: int = 5000) -> list[dict]:
        tag = (tag or "").strip().lstrip("#")
        prefix = tag[:2] if len(tag) >= 2 else tag
        deadline = asyncio.get_event_loop().time() + timeout_ms / 1000
        last_ranked: list[dict] = []
        while asyncio.get_event_loop().time() < deadline:
            raw = await self._find_topic_dropdown_candidates(page, tag)
            ranked = self._rank_topic_candidates(raw, tag)
            if ranked:
                await page.wait_for_timeout(200)
                return ranked
            if raw and prefix:
                has_relevant = any(
                    prefix in str(c.get("topic_text") or c.get("text") or "")
                    or tag in str(c.get("topic_text") or c.get("text") or "")
                    for c in raw
                )
                if has_relevant:
                    last_ranked = self._rank_topic_candidates(raw, tag)
                    if last_ranked:
                        return last_ranked
            await page.wait_for_timeout(280)
        return last_ranked

    async def _click_topic_suggestion(
        self, page: Page, tag: str, editor=None, before_nodes: int | None = None
    ) -> tuple[bool, str]:
        tag = (tag or "").strip().lstrip("#")
        candidates = await self._wait_for_topic_dropdown(page, tag, timeout_ms=3500)
        if not candidates:
            baijiahao_logger.warning(f"未找到可用的话题下拉项: #{tag}")
            return False, ""

        debug = [
            f"{c.get('topic_text', '')[:16]}@{int(c.get('x', 0))},{int(c.get('y', 0))}s={c.get('score')}"
            for c in candidates[:5]
        ]
        baijiahao_logger.info(f"话题下拉候选: {debug}")

        for c in candidates[:3]:
            x, y = c.get("x"), c.get("y")
            topic_text = str(c.get("topic_text") or "")
            if x is None or y is None or not topic_text:
                continue
            for dy in (0, -6):
                try:
                    baijiahao_logger.info(f"尝试鼠标点击话题项: #{topic_text} @({int(x)},{int(y + dy)})")
                    await self._mouse_click_xy(page, x, y + dy)
                    await page.wait_for_timeout(650)
                    if await self._topic_click_succeeded(editor, topic_text, before_nodes):
                        baijiahao_logger.info(f"已点选话题: #{topic_text}（匹配自 #{tag}）")
                        return True, topic_text
                    if await self._topic_click_succeeded(editor, tag, before_nodes):
                        baijiahao_logger.info(f"已点选话题: #{topic_text}（匹配自 #{tag}）")
                        return True, topic_text
                except Exception as exc:
                    baijiahao_logger.debug(f"点击候选失败: {exc}")
                    continue

        baijiahao_logger.warning(f"话题下拉点了但未生效: #{tag}；候选={debug}")
        return False, ""

    async def _clear_partial_topic_input(self, page: Page, editor, tag: str) -> None:
        await self._focus_body_editor(page, editor)
        n = len(tag or "") + 2
        for _ in range(max(n, 3)):
            try:
                await page.keyboard.press("Backspace")
                await page.wait_for_timeout(40)
            except Exception:
                break
        await page.wait_for_timeout(150)

    async def _ensure_editor_focused(self, page: Page, editable) -> bool:
        """确保光标在正文 contenteditable 内（话题插件只响应真实键盘事件）。"""
        for attempt in range(4):
            await self._blur_title_editor(page)
            await editable.scroll_into_view_if_needed()
            try:
                box = await editable.bounding_box()
                if box:
                    await page.mouse.click(
                        box["x"] + max(box["width"] - 12, box["width"] / 2),
                        box["y"] + max(box["height"] - 12, box["height"] / 2),
                    )
                else:
                    await editable.click(force=True)
            except Exception:
                await editable.click(force=True)
            await page.wait_for_timeout(180)
            await editable.evaluate(
                """(el) => {
                    el.focus();
                    const sel = window.getSelection();
                    const range = document.createRange();
                    range.selectNodeContents(el);
                    range.collapse(false);
                    sel.removeAllRanges();
                    sel.addRange(range);
                }"""
            )
            await page.wait_for_timeout(120)
            try:
                ok = await editable.evaluate(
                    """(el) => {
                        const a = document.activeElement;
                        return a === el || (a && el.contains(a));
                    }"""
                )
            except Exception:
                ok = False
            if ok:
                return True
            baijiahao_logger.debug(f"正文焦点未就绪，重试 ({attempt + 1}/4)")
        return False

    async def _snapshot_topic_list(self, page: Page) -> list[str]:
        try:
            return await page.evaluate(
                """() => Array.from(document.querySelectorAll('.topic-list .topic-item, .topic-item-wrap .topic-item'))
                    .filter(el => el.offsetParent !== null)
                    .map(el => ((el.querySelector('.topic-text') || el).innerText || '').trim())
                    .filter(Boolean)"""
            )
        except Exception:
            return []

    async def _type_topic_query(self, page: Page, editor, tag: str) -> None:
        """慢速键入 #话题，与 toutiao_uploader._type_topic_query 完全一致（page.keyboard.type）。"""
        tag = (tag or "").strip().lstrip("#")
        editable = await self._get_body_editable(page, editor)
        if not await self._ensure_editor_focused(page, editable):
            baijiahao_logger.warning("正文编辑器未能获得焦点，话题输入可能无效")

        before_list = await self._snapshot_topic_list(page)

        await page.keyboard.type("#", delay=140)
        await page.wait_for_timeout(500)
        for ch in tag:
            await page.keyboard.type(ch, delay=110)
            await page.wait_for_timeout(40)
        await page.wait_for_timeout(900)

        after_list = await self._snapshot_topic_list(page)

        try:
            info = await editable.evaluate(
                """(el, tag) => {
                    const text = (el.innerText || '').replace(/\\s+/g, '');
                    const active = document.activeElement;
                    const inEditor = active === el || (active && el.contains(active));
                    return {
                        hasHashTag: text.includes('#' + tag),
                        tail: text.slice(-Math.max(tag.length + 4, 10)),
                        activeTag: active ? active.tagName : '',
                        inEditor,
                    };
                }""",
                tag,
            )
            baijiahao_logger.info(
                f"话题输入 #{tag}: 末尾={info.get('tail')} 焦点={info.get('activeTag')} "
                f"在正文={info.get('inEditor')} 下拉变化={before_list[:3] != after_list[:3]}"
            )
            if after_list:
                baijiahao_logger.info(f"当前下拉前5项: {after_list[:5]}")
            elif before_list:
                baijiahao_logger.info(f"下拉未变化，仍显示: {before_list[:5]}")
        except Exception as exc:
            baijiahao_logger.debug(f"话题输入诊断失败: {exc}")

    async def _ensure_inline_after_topic(self, page: Page, editor) -> None:
        for key in ("ArrowRight", "ArrowRight"):
            try:
                await page.keyboard.press(key)
            except Exception:
                pass
        await page.wait_for_timeout(80)
        try:
            need_space = await editor.evaluate(
                """(el) => {
                    const sel = window.getSelection();
                    if (!sel || !sel.rangeCount) return true;
                    const range = sel.getRangeAt(0);
                    const pre = range.cloneRange();
                    pre.selectNodeContents(el);
                    pre.setEnd(range.startContainer, range.startOffset);
                    const text = pre.toString();
                    if (!text) return true;
                    const ch = text.slice(-1);
                    return !(ch === ' ' || ch === '\\u00a0');
                }"""
            )
        except Exception:
            need_space = True
        if need_space:
            await page.keyboard.type(" ", delay=30)

    async def _cleanup_leftover_topic_typing(self, editor, tag: str, picked_name: str) -> None:
        try:
            await editor.evaluate(
                """(el, tag) => {
                    const stripPrefixes = (text) => {
                        let result = text;
                        for (let i = tag.length; i >= 1; i--) {
                            result = result.split('#' + tag.slice(0, i)).join('');
                        }
                        result = result.split('#' + tag).join('');
                        return result;
                    };
                    const cleanNode = (node) => {
                        if (node.nodeType === Node.TEXT_NODE) {
                            node.textContent = stripPrefixes(node.textContent || '');
                            return;
                        }
                        if (node.nodeType !== Node.ELEMENT_NODE) return;
                        if (node.matches('a[data-bjh-box=\"topic\"], [data-bjh-box=\"topic\"]')) return;
                        for (const child of Array.from(node.childNodes)) cleanNode(child);
                    };
                    cleanNode(el);
                    el.dispatchEvent(new InputEvent('input', { bubbles: true }));
                }""",
                tag,
            )
        except Exception:
            pass

    async def insert_topics_in_body(self, page: Page, editor) -> None:
        """在正文末尾逐个键入 #话题 并鼠标点选下拉（参考头条实现）。"""
        tags = self._normalize_tags()
        if not tags:
            return

        editor = await self._get_body_editable(page, editor)

        existing = set()
        for node_tag in tags:
            if await self._editor_contains_confirmed_topic(editor, node_tag):
                existing.add(node_tag)
        tags = [t for t in tags if t not in existing]
        if not tags:
            baijiahao_logger.info("正文中已含全部话题，跳过插入")
            return

        baijiahao_logger.info(f"准备在正文内键入并点选话题（同行空格分隔）: {tags}")
        await self._move_caret_to_editor_end(page, editor)
        if not await self._ensure_editor_focused(page, editor):
            baijiahao_logger.warning("插入话题前未能聚焦正文，继续尝试键盘输入")
        await page.wait_for_timeout(150)

        for _ in range(6):
            try:
                trailing_break = await editor.evaluate(
                    """(el) => /[\\r\\n]+\\s*$/.test(el.innerText || '')"""
                )
            except Exception:
                trailing_break = False
            if not trailing_break:
                break
            await page.keyboard.press("Backspace")
            await page.wait_for_timeout(40)

        try:
            tail = ((await editor.inner_text()) or "")[-8:]
            if tail and not tail[-1].isspace():
                await page.keyboard.type(" ", delay=40)
        except Exception:
            await page.keyboard.type(" ", delay=40)
        await page.wait_for_timeout(200)

        added = []
        failed = []
        for idx, tag in enumerate(tags):
            try:
                if idx > 0:
                    try:
                        need_space = await editor.evaluate(
                            """(el) => {
                                const sel = window.getSelection();
                                if (!sel || !sel.rangeCount) return true;
                                const range = sel.getRangeAt(0);
                                const pre = range.cloneRange();
                                pre.selectNodeContents(el);
                                pre.setEnd(range.startContainer, range.startOffset);
                                const text = pre.toString();
                                if (!text) return true;
                                const ch = text.slice(-1);
                                return !(ch === ' ' || ch === '\\u00a0');
                            }"""
                        )
                    except Exception:
                        need_space = False
                    if need_space:
                        await page.keyboard.type(" ", delay=40)
                        await page.wait_for_timeout(120)

                before_nodes = await self._count_confirmed_topics(editor)
                await self._type_topic_query(page, editor, tag)
                clicked, picked_name = await self._click_topic_suggestion(
                    page, tag, editor=editor, before_nodes=before_nodes
                )

                if not clicked:
                    baijiahao_logger.warning(f"首次未点到，快速重试一次: #{tag}")
                    await self._clear_partial_topic_input(page, editor, tag)
                    await page.wait_for_timeout(400)
                    await self._type_topic_query(page, editor, tag)
                    clicked, picked_name = await self._click_topic_suggestion(
                        page, tag, editor=editor, before_nodes=before_nodes
                    )

                if clicked and await self._topic_click_succeeded(editor, picked_name or tag, before_nodes):
                    await self._cleanup_leftover_topic_typing(editor, tag, picked_name or tag)
                    added.append(picked_name or tag)
                    await page.wait_for_timeout(250)
                    await self._ensure_inline_after_topic(page, editor)
                else:
                    failed.append(tag)
                    raw = await self._find_topic_dropdown_candidates(page, tag)
                    visible = [str(c.get("text") or "")[:30] for c in raw[:5]]
                    if visible:
                        baijiahao_logger.warning(f"未点选到话题: #{tag}，平台下拉: {visible}")
                    else:
                        baijiahao_logger.warning(f"未点选到话题: #{tag}（未出现话题下拉）")
                    await self._clear_partial_topic_input(page, editor, tag)
            except Exception as exc:
                failed.append(tag)
                baijiahao_logger.warning(f"插入话题 #{tag} 失败: {exc}")
                await self._clear_partial_topic_input(page, editor, tag)

        if added:
            baijiahao_logger.success(f"已点选话题（同行空格分隔）: {added}")
        if failed:
            baijiahao_logger.warning(f"未能点选的话题: {failed}")
        if not added and failed:
            baijiahao_logger.warning("未能插入任何话题")

    async def _confirm_cover_dialog(self, page: Page) -> bool:
        confirm_candidates = [
            page.locator("div.cheetah-modal button").filter(has_text="确定").last,
            page.locator("div.cheetah-modal button").filter(has_text="确认").last,
            page.get_by_role("button", name="确定").last,
            page.get_by_role("button", name="确认").last,
        ]
        for btn in confirm_candidates:
            try:
                if not await btn.count() or not await btn.is_visible():
                    continue
                await btn.click(force=True)
                await page.wait_for_timeout(1200)
                return True
            except Exception:
                continue
        return False

    async def _select_single_cover_mode(self, page: Page) -> None:
        try:
            await page.get_by_text("单图", exact=True).first.scroll_into_view_if_needed(timeout=3000)
        except Exception:
            pass
        for label in ("单图",):
            try:
                single = page.locator("label.cheetah-radio-wrapper").filter(has_text=label).first
                if not await single.count():
                    single = page.get_by_text(label, exact=True).first
                if await single.count():
                    await single.click(force=True)
                    await page.wait_for_timeout(500)
                    return
            except Exception:
                continue

    async def _cover_placeholder_visible(self, page: Page) -> bool:
        choose_cover = page.get_by_text("选择封面", exact=True).first
        try:
            if await choose_cover.count():
                await choose_cover.scroll_into_view_if_needed(timeout=3000)
                return await choose_cover.is_visible()
        except Exception:
            pass
        return False

    async def _cover_already_set(self, page: Page) -> bool:
        if await self._cover_placeholder_visible(page):
            return False

        preview = page.locator('img[src*="picproxy"], img[src*="/bjh/picproxy"]').first
        try:
            if await preview.count() and await preview.is_visible():
                box = await preview.bounding_box()
                if box and box.get("width", 0) >= 80 and box.get("height", 0) >= 60:
                    return True
        except Exception:
            pass
        return False

    async def _open_cover_upload_modal(self, page: Page) -> None:
        try:
            await page.get_by_text("设置封面", exact=False).first.scroll_into_view_if_needed(timeout=3000)
        except Exception:
            pass

        choose_cover = page.get_by_text("选择封面", exact=True).first
        if not await choose_cover.count():
            raise RuntimeError("未找到「选择封面」入口")
        await choose_cover.scroll_into_view_if_needed()
        await choose_cover.click(force=True)
        await page.wait_for_timeout(1200)

        local_tab = page.get_by_text("正文/本地上传", exact=False).first
        if await local_tab.count() and await local_tab.is_visible():
            try:
                await local_tab.click(force=True)
                await page.wait_for_timeout(500)
            except Exception:
                pass

        modal = page.locator("div.cheetah-modal").last
        await modal.wait_for(state="visible", timeout=10000)

    async def _upload_cover_in_modal(self, page: Page, cover: Path) -> None:
        modal = page.locator("div.cheetah-modal").last
        file_input = modal.locator('input[type="file"][accept*="image"]').first
        if not await file_input.count():
            file_input = modal.locator('input[type="file"]').first
        if not await file_input.count():
            raise RuntimeError("封面弹窗中未找到图片上传控件")

        await file_input.set_input_files(str(cover))
        baijiahao_logger.info(f"已在封面弹窗中选择文件: {cover.name}")
        await page.wait_for_timeout(1500)

        if not await self._confirm_cover_dialog(page):
            raise RuntimeError("封面弹窗未能点击确定/确认")

        try:
            await modal.wait_for(state="hidden", timeout=10000)
        except Exception:
            await page.wait_for_timeout(1000)

    async def handle_cover(self, page: Page) -> None:
        if not self.cover_path:
            raise ValueError("百家号图文展示封面不能为空")

        cover = Path(str(self.cover_path))
        if not cover.exists():
            raise ValueError(f"封面文件不存在: {cover}")
        if cover.stat().st_size > 5 * 1024 * 1024:
            raise ValueError(f"封面超过 5MB: {cover}")

        baijiahao_logger.info(f"开始上传展示封面: {cover.name}")
        await self._select_single_cover_mode(page)

        if await self._cover_placeholder_visible(page):
            baijiahao_logger.info("检测到封面占位「选择封面」，开始上传")
        elif await self._cover_already_set(page):
            baijiahao_logger.info("展示封面预览已存在，跳过重复上传")
            return
        else:
            baijiahao_logger.info("未检测到封面预览，开始上传")

        await self._open_cover_upload_modal(page)
        await self._upload_cover_in_modal(page, cover)

        for _ in range(10):
            if await self._cover_already_set(page):
                baijiahao_logger.success(f"已上传展示封面: {cover.name}")
                return
            await page.wait_for_timeout(500)

        raise RuntimeError("百家号展示封面上传失败，请检查封面文件或页面是否改版")

    async def apply_ai_declaration(self, page: Page) -> None:
        if not self.ai_generated:
            return
        try:
            label = page.get_by_text("采用AI生成内容", exact=True).first
            if await label.count():
                await label.click(force=True)
                baijiahao_logger.info("已勾选「采用AI生成内容」")
                return
            checkbox = page.locator('input[type="checkbox"]').filter(
                has=page.get_by_text("采用AI生成内容")
            ).first
            if await checkbox.count():
                await checkbox.check(force=True)
                baijiahao_logger.info("已勾选 AI 创作声明")
        except Exception as exc:
            baijiahao_logger.warning(f"AI 创作声明勾选失败: {exc}")

    async def publish(self, page: Page) -> None:
        publish_button = page.locator("button.cheetah-public").filter(has_text="发布").first
        if not await publish_button.count():
            publish_button = page.get_by_role("button", name="发布").first
        await publish_button.wait_for(state="visible", timeout=15000)
        await publish_button.click()
        await page.wait_for_timeout(3000)
        baijiahao_logger.success("已点击文章发布")

    async def _open_article_page(self, page: Page) -> None:
        opened = False
        for url in BAIJIAHAO_ARTICLE_URLS:
            try:
                baijiahao_logger.info(f"正在打开百家号图文发布页: {url}")
                await page.goto(url, timeout=60000, wait_until="domcontentloaded")
                await _dismiss_overlays(page)

                if await page.get_by_text("注册/登录百家号").count():
                    raise RuntimeError("百家号未登录或 Cookie 失效，请重新登录账号")

                for _ in range(24):
                    if await self._is_article_page_ready(page):
                        opened = True
                        break
                    await page.wait_for_timeout(500)
                    await _dismiss_overlays(page)

                if opened:
                    break
            except RuntimeError:
                raise
            except Exception as exc:
                baijiahao_logger.warning(f"打开 {url} 失败: {exc}")

        if not opened:
            raise RuntimeError("无法打开百家号图文发布页，请检查账号权限或页面改版")

    async def upload(self, playwright: Playwright) -> None:
        if not (self.body or "").strip():
            raise ValueError("文章正文不能为空")
        if not self.title:
            raise ValueError("文章标题不能为空")
        if not self.cover_path:
            raise ValueError("百家号图文展示封面不能为空")

        browser = await _launch_browser(playwright, self.headless)
        context = await browser.new_context(
            storage_state=self.account_file,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/127.0.4324.150 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 900},
            locale="zh-CN",
        )
        context = await set_init_script(context)
        page = await context.new_page()

        await self._open_article_page(page)
        if self.dry_run:
            await _install_preview_guard(page)
            baijiahao_logger.info("已启用预览保护：发布按钮已禁用，请勿手动点击发布")

        await self.fill_title(page)
        await page.wait_for_timeout(500)
        await self.fill_body(page)
        await self.handle_cover(page)
        await self.apply_ai_declaration(page)
        await _dismiss_overlays(page)

        if self.dry_run:
            await _install_preview_guard(page)
            baijiahao_logger.warning("🛑 【仅预览不发布】已跳过点击发布按钮")
            baijiahao_logger.info("👀 请在浏览器窗口核对标题、正文、封面与创作声明")
            baijiahao_logger.info(
                "💡 百家号可能自动保存草稿；内容管理里出现记录≠已发布，请以「已发布」状态为准"
            )
            try:
                from pathlib import Path as _Path
                await page.screenshot(
                    full_page=True,
                    path=str(_Path(self.account_file).with_name("baijiahao_article_dry_run_preview.png")),
                )
            except Exception:
                pass
            for i in range(120):
                await asyncio.sleep(1)
                if i % 15 == 14:
                    try:
                        url = page.url or ""
                        if "success" in url or "publish" in url and "edit" not in url:
                            baijiahao_logger.error(
                                "⚠️ 检测到可能已跳转至发布成功页，请检查是否手动点击了发布"
                            )
                    except Exception:
                        pass
            baijiahao_logger.info("🛑 预览结束，关闭浏览器（脚本未点击发布）")
        else:
            if self.publish_date != 0:
                baijiahao_logger.warning("百家号图文定时发布暂未实现，将立即发布")
            await self.publish(page)
            baijiahao_logger.success("百家号文章发布流程完成")

        await context.storage_state(path=self.account_file)
        baijiahao_logger.info("cookie 更新完毕")
        await asyncio.sleep(1)
        await context.close()
        await browser.close()

    async def main(self):
        async with async_playwright() as playwright:
            await self.upload(playwright)
