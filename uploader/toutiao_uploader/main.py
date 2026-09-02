# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import os
from datetime import datetime
from pathlib import Path

from playwright.async_api import Page, Playwright, async_playwright

from conf import LOCAL_CHROME_HEADLESS, LOCAL_CHROME_PATH
from utils.base_social_media import set_init_script
from utils.log import toutiao_logger

TOUTIAO_HOME_URL = "https://mp.toutiao.com/"
TOUTIAO_LOGIN_URL = "https://mp.toutiao.com/auth/page/login"
TOUTIAO_DASHBOARD_PATH = "/profile_v4"
TOUTIAO_UPLOAD_URL = "https://mp.toutiao.com/profile_v4/xigua/upload-video"
TOUTIAO_ARTICLE_URL = "https://mp.toutiao.com/profile_v4/graphic/publish"
TOUTIAO_LOGIN_PATH = "/auth/page/login"


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


async def _dismiss_overlays(page: Page) -> None:
    """关闭常见弹窗/遮罩，避免挡住上传与发布按钮。"""
    close_candidates = [
        'button:has-text("知道了")',
        'button:has-text("我知道了")',
        'button:has-text("暂不")',
        'button:has-text("关闭")',
        'button:has-text("取消")',
        '[class*="close"]',
        '[aria-label="Close"]',
        ".byte-modal-close",
    ]
    for selector in close_candidates:
        try:
            loc = page.locator(selector).first
            if await loc.count() and await loc.is_visible():
                await loc.click(timeout=1000, force=True)
                await page.wait_for_timeout(300)
        except Exception:
            continue
    try:
        await page.keyboard.press("Escape")
    except Exception:
        pass


async def cookie_auth(account_file) -> bool:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(**_build_launch_kwargs(headless=LOCAL_CHROME_HEADLESS))
        try:
            context = await browser.new_context(storage_state=account_file)
            context = await set_init_script(context)
            page = await context.new_page()
            await page.goto(TOUTIAO_HOME_URL, timeout=60000)
            await page.wait_for_timeout(3000)
            url = page.url
            if TOUTIAO_LOGIN_PATH in url or "sso.toutiao.com" in url:
                toutiao_logger.error("[+] 今日头条 cookie 失效")
                return False
            if TOUTIAO_DASHBOARD_PATH in url:
                toutiao_logger.success("[+] 今日头条 cookie 有效")
                return True
            # 兜底：页面上是否有发布入口
            if await page.locator('a[href*="upload-video"], a[href*="graphic/publish"]').count():
                toutiao_logger.success("[+] 今日头条 cookie 有效")
                return True
            toutiao_logger.error("[+] 今日头条 cookie 失效")
            return False
        except Exception as exc:
            toutiao_logger.warning(f"[+] cookie 校验异常，按失效处理: {exc}")
            return False
        finally:
            await browser.close()


async def toutiao_cookie_gen(account_file):
    """CLI/本地调试用：打开登录页，手动登录后保存 cookie。"""
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(**_build_launch_kwargs(headless=False))
        context = await browser.new_context()
        context = await set_init_script(context)
        page = await context.new_page()
        await page.goto(TOUTIAO_LOGIN_URL)
        await page.pause()
        await context.storage_state(path=account_file)
        toutiao_logger.success("cookie saved")
        await context.close()
        await browser.close()


async def toutiao_setup(account_file, handle=False):
    if not os.path.exists(account_file) or not await cookie_auth(account_file):
        if not handle:
            return False
        toutiao_logger.error("cookie文件不存在或已失效，即将打开浏览器，请扫码登录")
        await toutiao_cookie_gen(account_file)
    return True


class TouTiaoVideo(object):
    def __init__(
        self,
        title,
        file_path,
        tags,
        publish_date: datetime,
        account_file,
        dry_run=False,
        description: str = "",
    ):
        self.title = (title or "")[:30]
        self.file_path = file_path
        self.tags = tags or []
        self.publish_date = publish_date
        self.account_file = account_file
        self.local_executable_path = LOCAL_CHROME_PATH
        self.headless = LOCAL_CHROME_HEADLESS if not dry_run else False
        self.dry_run = bool(dry_run)
        # 简介：优先用显式 description，否则用话题拼成描述
        if description:
            self.description = description
        elif self.tags:
            self.description = " ".join(f"#{t}" for t in self.tags)
        else:
            self.description = ""

    async def wait_for_upload(self, page: Page, timeout_ms: int = 10 * 60 * 1000) -> None:
        start = asyncio.get_event_loop().time()
        while (asyncio.get_event_loop().time() - start) * 1000 < timeout_ms:
            status = await page.evaluate(
                """() => {
                    const body = document.body ? document.body.innerText : '';
                    if (body.includes('上传失败')) return 'failed';
                    if (body.includes('上传成功')) return 'done';
                    const titleInput = document.querySelector('input[placeholder*="字符"]');
                    if (titleInput) return 'done';
                    return 'uploading';
                }"""
            )
            if status == "done":
                toutiao_logger.success("视频上传完毕")
                return
            if status == "failed":
                raise RuntimeError("视频上传失败")
            toutiao_logger.info("正在上传视频中...")
            await asyncio.sleep(2)
        raise TimeoutError("视频上传超时（10 分钟）")

    async def fill_title_and_desc(self, page: Page) -> None:
        # 标题 1~30 字符
        title_field = page.locator('input[placeholder*="字符"]').first
        await title_field.wait_for(timeout=30000)
        await title_field.click(force=True)
        await title_field.fill("")
        await page.wait_for_timeout(200)
        title_text = self.title or Path(str(self.file_path)).stem[:30]
        await title_field.fill(title_text)
        toutiao_logger.info(f"已填写标题: {title_text}")

        # 话题：依次输入后回车
        if self.tags:
            tags = [str(t).strip().lstrip("#") for t in self.tags if str(t).strip()][:5]
            topic_candidates = [
                page.locator('input[placeholder*="话题"]').first,
                page.locator('input[placeholder*="搜索话题"]').first,
                page.locator('[class*="topic"] input').first,
                page.locator('input[placeholder="请输入"]').first,
            ]
            try:
                topic_field = None
                for loc in topic_candidates:
                    try:
                        if await loc.count() and await loc.is_visible():
                            topic_field = loc
                            break
                    except Exception:
                        continue
                if topic_field:
                    for tag in tags:
                        await topic_field.click(force=True)
                        await page.wait_for_timeout(200)
                        # 慢速输入，给下拉搜索接口时间
                        await topic_field.fill("")
                        await page.wait_for_timeout(150)
                        await topic_field.type(tag, delay=100)
                        await page.wait_for_timeout(1000)
                        # 优先点下拉建议；等建议出现再点，避免点太快还是纯文本
                        suggestion = page.locator(
                            f'[class*="option"]:has-text("{tag}"), [class*="suggest"]:has-text("{tag}"), [class*="item"]:has-text("{tag}"), [role="option"]:has-text("{tag}")'
                        ).first
                        clicked = False
                        for _ in range(8):
                            try:
                                if await suggestion.count() and await suggestion.is_visible():
                                    await suggestion.click(timeout=2500)
                                    clicked = True
                                    break
                            except Exception:
                                pass
                            await page.wait_for_timeout(300)
                        if not clicked:
                            try:
                                await page.keyboard.press("ArrowDown")
                                await page.wait_for_timeout(200)
                                await page.keyboard.press("Enter")
                            except Exception:
                                await page.keyboard.press("Enter")
                        await page.wait_for_timeout(700)
                    toutiao_logger.info(f"已添加话题: {tags}")
                else:
                    toutiao_logger.warning("未找到视频页话题输入框，跳过话题")
            except Exception as exc:
                toutiao_logger.warning(f"话题填写失败（可忽略）: {exc}")

        # 简介
        if self.description:
            desc_field = page.locator('textarea[placeholder*="视频简介"]').first
            try:
                if await desc_field.count():
                    await desc_field.click(force=True)
                    await desc_field.fill(self.description[:400])
                    toutiao_logger.info("已填写视频简介")
            except Exception as exc:
                toutiao_logger.warning(f"简介填写失败（可忽略）: {exc}")

    async def handle_cover(self, page: Page) -> None:
        """封面必填：打开上传封面对话框，走「封面截取」默认第一帧。"""
        try:
            cover_trigger = page.locator("text=上传封面").first
            if not await cover_trigger.count():
                # 有的版本已有默认封面
                if await page.locator('img[class*="cover"], [class*="cover"] img').count():
                    toutiao_logger.info("已有封面，跳过封面设置")
                    return
            await cover_trigger.click(timeout=5000)
            await page.wait_for_timeout(2000)

            next_btn = page.locator('text=下一步').first
            if await next_btn.is_visible():
                await next_btn.click(force=True, timeout=5000)
                await page.wait_for_timeout(2500)

            # 封面编辑页与二次确认，优先点可见的「确定」
            for _ in range(2):
                ok_buttons = page.locator('text="确定"')
                count = await ok_buttons.count()
                clicked = False
                for i in range(count - 1, -1, -1):
                    btn = ok_buttons.nth(i)
                    try:
                        if await btn.is_visible():
                            await btn.click(force=True, timeout=3000)
                            clicked = True
                            await page.wait_for_timeout(1500)
                            break
                    except Exception:
                        continue
                if not clicked:
                    break

            # 等待对话框关闭
            for _ in range(15):
                if not await page.locator("text=封面编辑").first.is_visible():
                    break
                await page.wait_for_timeout(1000)

            await page.keyboard.press("Escape")
            toutiao_logger.info("封面设置完成")
        except Exception as exc:
            toutiao_logger.warning(f"封面设置失败（可忽略，页面可能已自动生成）: {exc}")
            try:
                await page.keyboard.press("Escape")
            except Exception:
                pass

    async def set_schedule_time(self, page: Page, publish_date: datetime) -> None:
        """尽力支持定时；UI 变动时仅记录警告，不阻断。"""
        try:
            # 常见：定时发布 开关 / 单选
            schedule_toggle = page.locator("text=定时发布").first
            if await schedule_toggle.count():
                await schedule_toggle.click(timeout=3000)
                await page.wait_for_timeout(800)

            # 尝试填时间 input
            date_str = publish_date.strftime("%Y-%m-%d %H:%M")
            time_input = page.locator(
                'input[placeholder*="时间"], input[placeholder*="选择"], input[type="text"][class*="date"]'
            ).first
            if await time_input.count():
                await time_input.click(force=True)
                await time_input.fill(date_str)
                await page.keyboard.press("Enter")
                toutiao_logger.info(f"已设置定时: {date_str}")
            else:
                toutiao_logger.warning("未找到定时时间输入框，将按立即发布处理")
        except Exception as exc:
            toutiao_logger.warning(f"定时设置失败: {exc}")

    async def publish(self, page: Page) -> None:
        await _dismiss_overlays(page)
        if self.publish_date != 0 and isinstance(self.publish_date, datetime):
            await self.set_schedule_time(page, self.publish_date)

        publish_btn = page.locator('button:has-text("发布")').last
        await publish_btn.scroll_into_view_if_needed()
        await page.wait_for_timeout(500)
        await publish_btn.click(force=True, timeout=15000)
        await page.wait_for_timeout(3000)
        toutiao_logger.success("已点击发布")

    async def upload(self, playwright: Playwright) -> None:
        launch_kwargs = _build_launch_kwargs(self.headless)
        browser = await playwright.chromium.launch(**launch_kwargs)
        context = await browser.new_context(
            storage_state=f"{self.account_file}",
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

        toutiao_logger.info(f"正在打开今日头条视频上传页... {TOUTIAO_UPLOAD_URL}")
        await page.goto(TOUTIAO_UPLOAD_URL, timeout=60000)
        await page.wait_for_timeout(2000)
        await _dismiss_overlays(page)

        if TOUTIAO_LOGIN_PATH in page.url or "sso.toutiao.com" in page.url:
            raise RuntimeError("今日头条 cookie 已失效，请重新登录")

        toutiao_logger.info(f"正在上传-------{self.title or Path(str(self.file_path)).name}")
        file_input = page.locator('input[type="file"]').first
        await file_input.set_input_files(str(self.file_path))
        await page.wait_for_timeout(2000)
        await self.wait_for_upload(page)
        await page.wait_for_timeout(2000)
        await _dismiss_overlays(page)

        # 基本信息
        try:
            await page.locator("text=基本信息").first.wait_for(timeout=30000)
        except Exception:
            pass

        await self.fill_title_and_desc(page)
        await self.handle_cover(page)
        await _dismiss_overlays(page)

        if self.dry_run:
            toutiao_logger.warning("🛑 【仅预览不发布】已跳过点击发布按钮")
            toutiao_logger.info("👀 请在浏览器窗口核对表单是否正确")
            try:
                await page.screenshot(
                    full_page=True,
                    path=str(Path(self.account_file).with_name("toutiao_dry_run_preview.png")),
                )
            except Exception:
                pass
            for _ in range(120):
                await asyncio.sleep(1)
            toutiao_logger.info("🛑 预览结束，关闭浏览器（未点击发布）")
        else:
            await self.publish(page)
            await page.wait_for_timeout(3000)
            toutiao_logger.success("视频发布流程完成")

        await context.storage_state(path=self.account_file)
        toutiao_logger.info("cookie 更新完毕")
        await asyncio.sleep(1)
        await context.close()
        await browser.close()

    async def main(self):
        async with async_playwright() as playwright:
            await self.upload(playwright)



# 今日头条图文「作品声明」可选值（与创作者后台文案一致）
TOUTIAO_WORK_STATEMENT_OPTIONS = (
    "取材网络",
    "引用站内",
    "个人观点，仅供参考",
    "引用AI",
    "虚构演绎，故事经历",
    "投资观点，仅供参考",
    "健康医疗分享，仅供参考",
)


class TouTiaoArticle(object):
    """今日头条图文文章发布（非微头条）。

    注意：图文页没有独立话题输入区，话题写在正文里（文末 #话题）。
    """

    def __init__(
        self,
        title,
        body,
        tags,
        publish_date: datetime | int,
        account_file,
        dry_run=False,
        cover_path=None,
        work_statements=None,
    ):
        self.title = (title or "")[:30]
        self.body = body or ""
        self.tags = tags or []
        self.publish_date = publish_date
        self.account_file = account_file
        self.local_executable_path = LOCAL_CHROME_PATH
        self.headless = LOCAL_CHROME_HEADLESS if not dry_run else False
        self.dry_run = bool(dry_run)
        self.cover_path = cover_path
        self.work_statements = self._normalize_work_statements(work_statements)

    @staticmethod
    def _normalize_work_statements(work_statements) -> list[str]:
        """规范化作品声明。

        头条图文页作品声明为单选；兼容传入字符串或列表，最终最多保留 1 项。
        """
        if not work_statements:
            return []
        if isinstance(work_statements, str):
            raw = [work_statements]
        else:
            try:
                raw = list(work_statements)
            except TypeError:
                raw = [work_statements]
        allowed = set(TOUTIAO_WORK_STATEMENT_OPTIONS)
        # 兼容前端可能传的短 key
        aliases = {
            "ai": "引用AI",
            "引用ai": "引用AI",
            "引用 AI": "引用AI",
            "网络": "取材网络",
            "站内": "引用站内",
            "个人观点": "个人观点，仅供参考",
            "虚构演绎": "虚构演绎，故事经历",
            "投资观点": "投资观点，仅供参考",
            "健康医疗": "健康医疗分享，仅供参考",
            "健康医疗分享": "健康医疗分享，仅供参考",
        }
        for item in raw:
            text = str(item or "").strip()
            if not text:
                continue
            text = aliases.get(text, aliases.get(text.lower(), text))
            if text not in allowed:
                matched = next(
                    (opt for opt in TOUTIAO_WORK_STATEMENT_OPTIONS if opt.startswith(text) or text in opt),
                    None,
                )
                if matched:
                    text = matched
                else:
                    toutiao_logger.warning(f"忽略未知作品声明项: {text}")
                    continue
            # 单选：取第一个合法项
            if len(raw) > 1:
                extra = [str(x).strip() for x in raw[1:] if str(x).strip()]
                if extra:
                    toutiao_logger.warning(f"作品声明为单选，仅使用「{text}」，忽略: {extra}")
            return [text]
        return []

    def _normalize_tags(self) -> list[str]:
        tags = [str(t).strip().lstrip("#") for t in (self.tags or []) if str(t).strip()]
        # 头条图文正文内话题不宜过多
        return tags[:10]

    async def fill_title(self, page: Page) -> None:
        candidates = [
            page.locator('input[placeholder*="标题"]').first,
            page.locator('textarea[placeholder*="标题"]').first,
            page.locator('input[placeholder*="请输入文章标题"]').first,
            page.locator('input[placeholder*="字符"]').first,
            page.get_by_placeholder("请输入标题").first,
        ]
        title_field = None
        for loc in candidates:
            try:
                if await loc.count() and await loc.is_visible():
                    title_field = loc
                    break
            except Exception:
                continue
        if not title_field:
            raise RuntimeError("未找到文章标题输入框")

        await title_field.click(force=True)
        await title_field.fill("")
        await page.wait_for_timeout(200)
        title_text = self.title or "未命名文章"
        await title_field.fill(title_text)
        toutiao_logger.info(f"已填写文章标题: {title_text}")

    async def _find_editor(self, page: Page):
        """定位正文富文本编辑区（含 iframe）。"""
        selectors = [
            '[contenteditable="true"]',
            'div[role="textbox"]',
            '.ProseMirror',
            '.ql-editor',
            '.public-DraftEditor-content',
            '.DraftEditor-root',
            'div[class*="editor"] [contenteditable="true"]',
            'div[class*="editor-content"]',
            'div[class*="syl-editor"]',
        ]
        for sel in selectors:
            loc = page.locator(sel).first
            try:
                if await loc.count() and await loc.is_visible():
                    return page, loc
            except Exception:
                continue

        for frame in page.frames:
            if frame == page.main_frame:
                continue
            for sel in selectors:
                try:
                    loc = frame.locator(sel).first
                    if await loc.count():
                        return frame, loc
                except Exception:
                    continue
        return None, None

    async def _paste_or_type_text(self, page: Page, editor, text: str) -> None:
        """把纯文本写入编辑器（不含话题识别逻辑）。"""
        filled = False
        try:
            try:
                await page.context.grant_permissions(["clipboard-read", "clipboard-write"])
            except Exception:
                pass
            await editor.click(force=True)
            await page.wait_for_timeout(200)
            await page.keyboard.press("Control+A")
            await page.keyboard.press("Backspace")
            await page.evaluate(
                """async (t) => { await navigator.clipboard.writeText(t); }""",
                text,
            )
            await page.keyboard.press("Control+V")
            await page.wait_for_timeout(800)
            filled = True
            toutiao_logger.info("正文已通过剪贴板粘贴")
        except Exception as exc:
            toutiao_logger.warning(f"剪贴板粘贴正文失败，尝试键盘输入: {exc}")

        if not filled:
            try:
                await editor.click(force=True)
                await page.keyboard.press("Control+A")
                await page.keyboard.press("Backspace")
                chunk_size = 200
                for i in range(0, len(text), chunk_size):
                    await page.keyboard.type(text[i : i + chunk_size], delay=5)
                filled = True
                toutiao_logger.info("正文已通过键盘输入")
            except Exception as exc:
                toutiao_logger.warning(f"键盘输入正文失败，尝试 DOM 写入: {exc}")

        if not filled:
            await editor.evaluate(
                """(el, t) => {
                    el.focus();
                    el.innerText = t;
                    el.dispatchEvent(new InputEvent('input', { bubbles: true, data: t }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                }""",
                text,
            )
            toutiao_logger.info("正文已通过 DOM 写入")

    async def _move_caret_to_editor_end(self, page: Page, editor) -> None:
        try:
            await editor.click(force=True)
        except Exception:
            pass
        await page.wait_for_timeout(100)
        # 多次 End / Ctrl+End，兼容不同编辑器
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
                    range.selectNodeContents(el);
                    range.collapse(false);
                    sel.removeAllRanges();
                    sel.addRange(range);
                }"""
            )
        except Exception:
            pass
        await page.wait_for_timeout(150)

    async def _ensure_inline_after_topic(self, page: Page, editor) -> None:
        """话题点选后尽量保持同一行：去掉误插入的换行/空段，只留空格间隔。"""
        # 先移出话题 chip
        for key in ("ArrowRight", "ArrowRight"):
            try:
                await page.keyboard.press(key)
            except Exception:
                pass
        await page.wait_for_timeout(80)

        # 若光标落在新空段/换行后，连按 Backspace 合并回上一行
        for _ in range(3):
            try:
                need_join = await editor.evaluate(
                    """(el) => {
                        const sel = window.getSelection();
                        if (!sel || !sel.rangeCount) return false;
                        const range = sel.getRangeAt(0);
                        // 当前块是否几乎为空（话题后被拆成新段落）
                        let node = range.startContainer;
                        if (node && node.nodeType === 3) node = node.parentElement;
                        while (node && node !== el) {
                            const tag = (node.tagName || '').toUpperCase();
                            if (tag === 'P' || tag === 'DIV' || tag === 'LI' || tag === 'SECTION') {
                                const t = (node.innerText || '').replace(/\\u00a0/g, ' ').trim();
                                // 空段 / 只有零宽字符
                                if (!t) return true;
                                break;
                            }
                            node = node.parentElement;
                        }
                        // 光标前一个字符是换行
                        try {
                            const pre = range.cloneRange();
                            pre.selectNodeContents(el);
                            pre.setEnd(range.startContainer, range.startOffset);
                            const text = pre.toString();
                            if (text.endsWith('\\n') || text.endsWith('\\r')) return true;
                        } catch (e) {}
                        return false;
                    }"""
                )
            except Exception:
                need_join = False
            if not need_join:
                break
            try:
                await page.keyboard.press("Backspace")
                await page.wait_for_timeout(60)
            except Exception:
                break

        # 保证话题之间只有一个空格，绝不回车
        try:
            need_space = await editor.evaluate(
                """(el) => {
                    const sel = window.getSelection();
                    if (!sel || !sel.rangeCount) return true;
                    const range = sel.getRangeAt(0);
                    try {
                        const pre = range.cloneRange();
                        pre.selectNodeContents(el);
                        pre.setEnd(range.startContainer, range.startOffset);
                        const text = pre.toString();
                        if (!text) return true;
                        const ch = text.slice(-1);
                        return !(ch === ' ' || ch === '\\u00a0');
                    } catch (e) {
                        return true;
                    }
                }"""
            )
        except Exception:
            need_space = True
        if need_space:
            try:
                await page.keyboard.type(" ", delay=30)
            except Exception:
                pass

    async def _collapse_topic_line_breaks(self, page: Page, editor) -> None:
        """把文末被拆成多行的话题标签尽量合并到同一行（空格分隔）。"""
        try:
            changed = await editor.evaluate(
                """(el) => {
                    if (!el) return false;
                    // 找出疑似话题节点
                    const isTopic = (node) => {
                        if (!node || node.nodeType !== 1) return false;
                        const t = (node.innerText || node.textContent || '').replace(/\\s+/g, ' ').trim();
                        if (!t || t.length > 40 || !t.includes('#')) return false;
                        const cls = String(node.className || '');
                        const href = String(node.getAttribute('href') || '');
                        return (
                            node.tagName === 'A'
                            || /topic|hash|mention|tag/i.test(cls)
                            || /topic|hashtag/i.test(href)
                            || node.hasAttribute('data-topic')
                            || node.hasAttribute('data-hashtag')
                            || node.getAttribute('contenteditable') === 'false'
                        );
                    };
                    const topics = Array.from(el.querySelectorAll('a, span, em, strong, i')).filter(isTopic);
                    if (topics.length < 2) return false;

                    // 若话题各自落在独立块级容器里，尝试把它们挪到同一个段落
                    const blockOf = (node) => {
                        let n = node;
                        while (n && n.parentElement && n.parentElement !== el) {
                            const tag = (n.parentElement.tagName || '').toUpperCase();
                            if (tag === 'P' || tag === 'DIV' || tag === 'LI' || tag === 'SECTION') {
                                // 只认“主要只含该话题”的块
                                const pt = (n.parentElement.innerText || '').replace(/\\s+/g, ' ').trim();
                                const nt = (node.innerText || '').replace(/\\s+/g, ' ').trim();
                                if (pt === nt || pt === ('#' + nt) || pt.length <= nt.length + 2) {
                                    return n.parentElement;
                                }
                            }
                            n = n.parentElement;
                        }
                        return null;
                    };

                    const blocks = [];
                    for (const t of topics) {
                        const b = blockOf(t);
                        if (b && !blocks.includes(b)) blocks.push(b);
                    }
                    if (blocks.length < 2) return false;

                    // 用第一个块承接后续话题，块之间用空格，不换行
                    const host = blocks[0];
                    for (let i = 1; i < blocks.length; i++) {
                        const b = blocks[i];
                        // 在 host 末尾加空格 + 话题节点
                        host.appendChild(document.createTextNode(' '));
                        // 把块内话题节点挪过去
                        const nodes = Array.from(b.childNodes);
                        for (const n of nodes) {
                            host.appendChild(n);
                        }
                        try { b.remove(); } catch (e) {
                            try { b.parentElement && b.parentElement.removeChild(b); } catch (e2) {}
                        }
                    }
                    el.dispatchEvent(new InputEvent('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    return true;
                }"""
            )
            if changed:
                toutiao_logger.info("已将多行话题合并为同一行（空格分隔）")
                await page.wait_for_timeout(200)
        except Exception as exc:
            toutiao_logger.debug(f"合并话题换行失败（可忽略）: {exc}")

    async def _find_topic_dropdown_candidates(self, page: Page, tag: str) -> list[dict]:
        """收集话题下拉候选项（返回坐标+文案），不依赖特定 class。"""
        try:
            items = await page.evaluate(
                """(tag) => {
                    const needle = String(tag || '').trim();
                    const isVis = (el) => {
                        const r = el.getBoundingClientRect();
                        const s = window.getComputedStyle(el);
                        return r.width >= 20 && r.height >= 16
                            && s.visibility !== 'hidden'
                            && s.display !== 'none'
                            && Number(s.opacity || 1) > 0.05
                            && r.bottom > 0 && r.top < (window.innerHeight + 20)
                            && r.right > 0 && r.left < window.innerWidth;
                    };
                    // 优先找“浮层”容器：高 z-index / fixed / absolute 的列表
                    const all = Array.from(document.querySelectorAll('body *'));
                    const layers = all.filter(el => {
                        if (!isVis(el)) return false;
                        const s = window.getComputedStyle(el);
                        const pos = s.position;
                        const z = parseInt(s.zIndex || '0', 10) || 0;
                        const r = el.getBoundingClientRect();
                        const cls = String(el.className || '');
                        const looksFloat = pos === 'fixed' || pos === 'absolute' || z >= 10
                            || /mention|suggest|dropdown|popover|popup|panel|select|topic|hashtag|at-list|tag/i.test(cls);
                        // 下拉层通常不太大也不全屏
                        return looksFloat && r.height >= 30 && r.height < window.innerHeight * 0.85
                            && r.width >= 80 && r.width < window.innerWidth * 0.9;
                    });

                    const rowSelector = 'li, [role="option"], [class*="item"], [class*="option"], div, span, a, p';
                    const rows = [];
                    const pushRow = (el, preferLayer) => {
                        if (!isVis(el)) return;
                        const t = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
                        if (!t || t.length > 50) return;
                        // 排除明显不是话题的
                        if (/发布|定时|封面|上传|取消|确定|保存|预览/.test(t) && t.length < 8) return;
                        const r = el.getBoundingClientRect();
                        // 太靠上的导航栏跳过
                        if (r.top < 40) return;
                        // 行高一般不会特别高
                        if (r.height > 80) return;
                        let score = 0;
                        if (preferLayer) score += 5;
                        if (needle && (t.includes(needle) || t.includes('#' + needle))) score += 20;
                        if (t.startsWith('#') || t.includes('#')) score += 3;
                        if (el.tagName === 'LI' || el.getAttribute('role') === 'option') score += 4;
                        const cls = String(el.className || '');
                        if (/item|option|mention|topic|tag|hashtag/i.test(cls)) score += 3;
                        // 文本过长更像段落
                        if (t.length <= 20) score += 2;
                        rows.push({
                            text: t,
                            x: r.left + r.width / 2,
                            y: r.top + r.height / 2,
                            w: r.width,
                            h: r.height,
                            top: r.top,
                            score,
                        });
                    };

                    if (layers.length) {
                        // 取最大/最靠上的几个浮层
                        layers.sort((a, b) => {
                            const za = parseInt(getComputedStyle(a).zIndex || '0', 10) || 0;
                            const zb = parseInt(getComputedStyle(b).zIndex || '0', 10) || 0;
                            return zb - za;
                        });
                        for (const layer of layers.slice(0, 8)) {
                            layer.querySelectorAll(rowSelector).forEach(el => pushRow(el, true));
                        }
                    }
                    // 全局再扫一遍短文本可见节点（防止层识别失败）
                    all.filter(isVis).forEach(el => pushRow(el, false));

                    // 去重：相近坐标+相同文案
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
            toutiao_logger.debug(f"收集话题下拉失败: {exc}")
            return []

    async def _mouse_click_xy(self, page: Page, x: float, y: float) -> None:
        """用真实鼠标点击坐标（比 element.click 更容易点到浮层）。"""
        await page.mouse.move(float(x), float(y), steps=8)
        await page.wait_for_timeout(120)
        await page.mouse.down()
        await page.wait_for_timeout(50)
        await page.mouse.up()
        await page.wait_for_timeout(350)

    def _is_real_topic_dropdown_item(self, text: str, tag: str = "") -> bool:
        """判断文案是否像真正的话题下拉项。

        成功项常见形态：#角色道具# 0讨论 / #家居摆件# 1.0万讨论
        失败日志里像「#道具定制」无讨论数、或侧边推荐文案，都要过滤掉。
        """
        t = (text or "").replace("\n", " ").strip()
        if not t or len(t) > 40:
            return False
        # 明显不是话题下拉
        junk = (
            "发布", "定时", "封面", "上传", "取消", "确定", "保存", "预览",
            "回到顶部", "正能量", "上联", "下联", "试管", "方言", "共 ",
        )
        if any(k in t for k in junk):
            return False
        # 头条话题下拉几乎都带「讨论」
        if "讨论" in t and "#" in t:
            return True
        # 没有「讨论」时，必须是很短的 #话题 形态，且包含目标词
        tag = (tag or "").strip().lstrip("#")
        if tag and (tag in t) and t.startswith("#") and len(t) <= len(tag) + 4:
            # 仅 #话题 本身，可能是编辑器内已输入的纯文本，不当作下拉项
            return False
        return False

    def _rank_topic_candidates(self, candidates: list[dict], tag: str) -> list[dict]:
        """只保留真正的下拉项，并按相关度排序。"""
        tag = (tag or "").strip().lstrip("#")
        ranked = []
        for c in candidates or []:
            text = str(c.get("text") or "")
            if not self._is_real_topic_dropdown_item(text, tag):
                continue
            score = int(c.get("score") or 0)
            if tag and tag in text:
                score += 30
            if "讨论" in text:
                score += 20
            # 更像「#话题# 数字讨论」
            if text.count("#") >= 2:
                score += 10
            ranked.append({**c, "score": score})
        ranked.sort(key=lambda x: x.get("score", 0), reverse=True)
        return ranked

    async def _count_topic_nodes_in_editor(self, editor) -> int:
        """统计编辑器内已确认的话题节点数（用于判断点选是否真正生效）。"""
        try:
            return int(
                await editor.evaluate(
                    """(el) => {
                        if (!el) return 0;
                        const sels = [
                            '[data-topic]',
                            '[data-hashtag]',
                            'a[href*="topic"]',
                            'a[href*="hashtag"]',
                            '[class*="topic"]',
                            '[class*="hashtag"]',
                            '[class*="mention"]',
                            '[data-slate-type*="topic"]',
                            '[data-type*="topic"]',
                        ];
                        let n = 0;
                        for (const s of sels) {
                            try { n += el.querySelectorAll(s).length; } catch (e) {}
                        }
                        const all = Array.from(el.querySelectorAll('a, span, em, strong, i'));
                        for (const node of all) {
                            const t = (node.innerText || node.textContent || '').replace(/\\s+/g, ' ').trim();
                            if (!t || t.length > 40 || !t.includes('#')) continue;
                            const cls = String(node.className || '');
                            const attr = (node.getAttribute('contenteditable') || '');
                            if (node.tagName === 'A' || /topic|hash|mention|tag/i.test(cls) || attr === 'false') {
                                n += 1;
                            }
                        }
                        return n;
                    }"""
                )
            )
        except Exception:
            return 0

    async def _editor_contains_confirmed_topic(self, editor, tag: str) -> bool:
        """判断话题是否已从纯文本变成可识别的话题标签节点。"""
        tag = (tag or "").strip().lstrip("#")
        if not tag:
            return False
        try:
            return bool(
                await editor.evaluate(
                    """(el, tag) => {
                        if (!el) return false;
                        const needle = String(tag || '').trim();
                        const nodes = Array.from(el.querySelectorAll(
                            'a, span, em, strong, i, [data-topic], [data-hashtag], [class*="topic"], [class*="hashtag"], [class*="mention"]'
                        ));
                        for (const node of nodes) {
                            const t = (node.innerText || node.textContent || '').replace(/\\s+/g, ' ').trim();
                            if (!t || t.length > 50) continue;
                            if (!(t.includes(needle) || t.includes('#' + needle))) continue;
                            const cls = String(node.className || '');
                            const href = String(node.getAttribute('href') || '');
                            const ce = node.getAttribute('contenteditable');
                            if (
                                node.tagName === 'A'
                                || /topic|hash|mention|tag/i.test(cls)
                                || /topic|hashtag/i.test(href)
                                || node.hasAttribute('data-topic')
                                || node.hasAttribute('data-hashtag')
                                || ce === 'false'
                            ) {
                                return true;
                            }
                        }
                        return false;
                    }""",
                    tag,
                )
            )
        except Exception:
            return False

    async def _topic_click_succeeded(self, editor, tag: str, before_nodes: int | None) -> bool:
        if editor is None:
            return False
        if await self._editor_contains_confirmed_topic(editor, tag):
            return True
        if before_nodes is not None:
            after_nodes = await self._count_topic_nodes_in_editor(editor)
            if after_nodes > before_nodes:
                return True
        return False

    async def _wait_for_topic_dropdown(self, page: Page, tag: str, timeout_ms: int = 3500) -> list[dict]:
        """等待真正的话题下拉项出现；过滤页面杂讯。"""
        tag = (tag or "").strip().lstrip("#")
        deadline = asyncio.get_event_loop().time() + timeout_ms / 1000
        last: list[dict] = []
        while asyncio.get_event_loop().time() < deadline:
            raw = await self._find_topic_dropdown_candidates(page, tag)
            ranked = self._rank_topic_candidates(raw, tag)
            if ranked:
                # 有「讨论」的项即可点，不必死等稳定两次
                if any("讨论" in str(c.get("text") or "") for c in ranked):
                    await page.wait_for_timeout(200)
                    return ranked
                last = ranked
            await page.wait_for_timeout(250)
        return last

    async def _click_topic_suggestion(self, page: Page, tag: str, editor=None, before_nodes: int | None = None) -> bool:
        """输入 #话题 后点下拉建议。失败快速返回，避免空转。"""
        tag = (tag or "").strip().lstrip("#")

        candidates = await self._wait_for_topic_dropdown(page, tag, timeout_ms=3500)
        if not candidates:
            # Playwright 轻量兜底一次
            try:
                opts = page.locator('[role="option"]')
                n = await opts.count()
                for i in range(min(n, 6)):
                    opt = opts.nth(i)
                    if not await opt.is_visible():
                        continue
                    t = ((await opt.inner_text()) or "").strip().replace("\n", " ")
                    if not self._is_real_topic_dropdown_item(t, tag):
                        continue
                    if tag and tag not in t:
                        continue
                    box = await opt.bounding_box()
                    if not box:
                        continue
                    toutiao_logger.info(f"尝试点击 role=option: 「{t[:24]}」")
                    await self._mouse_click_xy(
                        page, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
                    )
                    await page.wait_for_timeout(600)
                    if await self._topic_click_succeeded(editor, tag, before_nodes):
                        toutiao_logger.info(f"已点选话题建议: #{tag}（{t[:30]}）")
                        return True
            except Exception:
                pass
            toutiao_logger.warning(f"未找到可用的话题下拉项: #{tag}")
            return False

        debug = [
            f"{c.get('text','')[:20]}@{int(c.get('x',0))},{int(c.get('y',0))}s={c.get('score')}"
            for c in candidates[:5]
        ]
        toutiao_logger.info(f"话题下拉候选: {debug}")

        # 最多试前 2 个真实候选项，每个只点中心 1 次（必要时再偏一点）
        for c in candidates[:2]:
            x, y = c.get("x"), c.get("y")
            text = str(c.get("text") or "")
            if x is None or y is None:
                continue
            for dy in (0, -6):
                toutiao_logger.info(f"尝试鼠标点击话题项: 「{text[:24]}」 @({int(x)},{int(y + dy)})")
                try:
                    await self._mouse_click_xy(page, x, y + dy)
                    await page.wait_for_timeout(650)
                    if await self._topic_click_succeeded(editor, tag, before_nodes):
                        toutiao_logger.info(f"已点选话题建议: #{tag}（{text[:30]}）")
                        return True
                except Exception as exc:
                    toutiao_logger.debug(f"点击候选失败: {exc}")
                    continue
            # 该候选项点了两次仍无效，换下一个，不再死磕

        toutiao_logger.warning(f"话题下拉点了但未生效: #{tag}；候选={debug}")
        return False

    async def _clear_partial_topic_input(self, page: Page, tag: str) -> None:
        """清掉未成功转成标签的 #话题 纯文本，避免残留。"""
        n = len(tag or "") + 2  # # + tag + 可能空格
        for _ in range(max(n, 3)):
            try:
                await page.keyboard.press("Backspace")
                await page.wait_for_timeout(30)
            except Exception:
                break
        await page.wait_for_timeout(150)

    async def _type_topic_query(self, page: Page, tag: str) -> None:
        """慢速输入 #话题，给搜索下拉充足过滤时间。"""
        await page.keyboard.type("#", delay=140)
        await page.wait_for_timeout(500)
        for ch in tag:
            await page.keyboard.type(ch, delay=110)
            await page.wait_for_timeout(40)
        await page.wait_for_timeout(900)

    async def _screenshot_topic_debug(self, page: Page, tag: str) -> None:
        try:
            path = Path(self.account_file).with_name(f"toutiao_topic_fail_{tag[:12]}.png")
            await page.screenshot(path=str(path), full_page=False)
            toutiao_logger.warning(f"话题点选失败截图: {path}")
        except Exception:
            pass

    async def insert_topics_in_body(self, page: Page, editor) -> None:
        """在正文末尾逐个键入 #话题并点选下拉。

        注意：确认话题只能点下拉，不能回车/空格确认；
        话题与话题之间只用空格分隔，不要回车换行。
        目标形态：#氛围感# #手工作品# #模型定制#（同一行）
        """
        tags = self._normalize_tags()
        if not tags:
            return

        try:
            existing_text = (await editor.inner_text()) or ""
        except Exception:
            existing_text = self.body or ""
        existing = set()
        for part in existing_text.replace("\n", " ").split():
            if part.startswith("#") and len(part) > 1:
                existing.add(part.lstrip("#").strip(",.，。"))
        tags = [t for t in tags if t not in existing]
        if not tags:
            toutiao_logger.info("正文中已含全部话题，跳过插入")
            return

        toutiao_logger.info(f"准备在正文内键入并点选话题（同行空格分隔）: {tags}")
        # 光标移到正文末尾；正文与话题之间最多一个空格，话题之间也不换行
        await self._move_caret_to_editor_end(page, editor)
        await page.wait_for_timeout(150)

        # 去掉正文末尾多余换行，避免话题从新行开始后继续被拆行
        for _ in range(6):
            try:
                trailing_break = await editor.evaluate(
                    """(el) => {
                        const t = (el.innerText || '');
                        return /[\\r\\n]+\\s*$/.test(t);
                    }"""
                )
            except Exception:
                trailing_break = False
            if not trailing_break:
                break
            try:
                await page.keyboard.press("Backspace")
                await page.wait_for_timeout(40)
            except Exception:
                break

        try:
            tail = ""
            try:
                tail = ((await editor.inner_text()) or "")[-8:]
            except Exception:
                pass
            # 仅在末尾非空白时补一个空格；末尾已是空格则不再加
            if tail and not tail[-1].isspace():
                await page.keyboard.type(" ", delay=40)
        except Exception:
            await page.keyboard.type(" ", delay=40)
        await page.wait_for_timeout(200)

        added = []
        failed = []
        for idx, tag in enumerate(tags):
            try:
                # 绝对不要 Enter / Ctrl+End；第二个及以后话题的间隔由
                # _ensure_inline_after_topic 在上一个话题后写入的空格负责
                if idx > 0:
                    # 双保险：若上一步没留下空格，这里再补一个（仍不回车）
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

                before_nodes = await self._count_topic_nodes_in_editor(editor)
                await self._type_topic_query(page, tag)

                # 每个话题：点选最多 1 次完整尝试 + 1 次快速重试，失败立刻跳过
                clicked = await self._click_topic_suggestion(
                    page, tag, editor=editor, before_nodes=before_nodes
                )

                if not clicked:
                    toutiao_logger.warning(f"首次未点到，快速重试一次: #{tag}")
                    await self._clear_partial_topic_input(page, tag)
                    await page.wait_for_timeout(300)
                    await self._type_topic_query(page, tag)
                    clicked = await self._click_topic_suggestion(
                        page, tag, editor=editor, before_nodes=before_nodes
                    )

                if clicked and await self._topic_click_succeeded(editor, tag, before_nodes):
                    added.append(tag)
                    await page.wait_for_timeout(250)
                    # 合并误插入换行，并只补一个空格给下一个话题
                    await self._ensure_inline_after_topic(page, editor)
                else:
                    failed.append(tag)
                    await self._screenshot_topic_debug(page, tag)
                    toutiao_logger.warning(f"未点选到话题下拉: #{tag}，已跳过（不继续死磕）")
                    await self._clear_partial_topic_input(page, tag)
            except Exception as exc:
                failed.append(tag)
                toutiao_logger.warning(f"插入话题 #{tag} 失败: {exc}")

        # 兜底：若编辑器仍把话题拆成多行，尝试 DOM 合并到同一行
        if len(added) >= 2:
            await self._collapse_topic_line_breaks(page, editor)

        if added:
            toutiao_logger.success(f"已点选话题（同行空格分隔）: {added}")
        if failed:
            toutiao_logger.warning(f"未能点选的话题: {failed}")
        if not added:
            toutiao_logger.warning("未能插入任何话题")

    async def fill_body(self, page: Page) -> None:
        """先填纯正文，再在文末逐个键入 #话题并鼠标点选下拉。"""
        body_text = (self.body or "").rstrip()
        if not body_text.strip() and not self._normalize_tags():
            raise ValueError("文章正文不能为空")

        _frame, editor = await self._find_editor(page)
        if not editor:
            await page.wait_for_timeout(3000)
            _frame, editor = await self._find_editor(page)
        if not editor:
            raise RuntimeError("未找到文章正文编辑器")

        await editor.scroll_into_view_if_needed()
        await page.wait_for_timeout(300)

        if body_text.strip():
            await self._paste_or_type_text(page, editor, body_text)
        else:
            await editor.click(force=True)
            await page.keyboard.press("Control+A")
            await page.keyboard.press("Backspace")

        try:
            content = await editor.inner_text()
            if body_text.strip() and content and len(content.strip()) >= min(5, len(body_text)):
                toutiao_logger.success(f"正文写入校验通过（约 {len(content.strip())} 字）")
            elif body_text.strip():
                toutiao_logger.warning(
                    f"正文读回长度偏短（{len((content or '').strip())}），请 dry_run 人工确认"
                )
        except Exception:
            pass

        await self.insert_topics_in_body(page, editor)

    async def _confirm_cover_dialog(self, page: Page) -> None:
        """封面裁剪/确认弹窗：尽量点掉「确定/完成/确认」。"""
        await page.wait_for_timeout(600)
        # 有的版本先出现「本地上传」tab
        for tab_label in ("本地上传", "上传图片", "图片上传"):
            try:
                tab = page.get_by_text(tab_label, exact=True).first
                if await tab.count() and await tab.is_visible():
                    await tab.click(timeout=1500)
                    await page.wait_for_timeout(300)
            except Exception:
                continue

        for _ in range(4):
            clicked = False
            for label in ("确定", "完成", "确认", "使用", "保存", "下一步"):
                candidates = [
                    page.get_by_role("button", name=label),
                    page.locator(f'button:has-text("{label}")'),
                    page.locator(f'[class*="modal"] button:has-text("{label}")'),
                    page.locator(f'[class*="dialog"] button:has-text("{label}")'),
                    page.locator(f'text="{label}"'),
                ]
                for loc in candidates:
                    try:
                        count = await loc.count()
                        for i in range(count - 1, -1, -1):
                            btn = loc.nth(i)
                            if not await btn.is_visible():
                                continue
                            await btn.click(timeout=2500, force=True)
                            clicked = True
                            await page.wait_for_timeout(900)
                            break
                        if clicked:
                            break
                    except Exception:
                        continue
                if clicked:
                    break
            if not clicked:
                break

    async def _find_cover_section(self, page: Page):
        """定位「展示封面」所在区域（返回 Locator），避免误点正文插图按钮。"""
        section_selectors = [
            'div:has-text("展示封面"):has-text("单图"):has-text("无封面")',
            'div:has-text("展示封面"):has-text("优质的封面")',
            'div:has-text("展示封面"):has-text("单图")',
            'section:has-text("展示封面")',
        ]
        best = None
        best_h = 10**9
        for sel in section_selectors:
            try:
                loc = page.locator(sel)
                count = await loc.count()
                for i in range(min(count, 8)):
                    item = loc.nth(i)
                    box = await item.bounding_box()
                    if not box:
                        continue
                    h = box.get("height") or 0
                    w = box.get("width") or 0
                    # 封面区通常是中等高度的表单项，不是整页
                    if 80 < h < 520 and w > 160:
                        if h < best_h:
                            best = item
                            best_h = h
            except Exception:
                continue
        return best

    async def _cover_state(self, page: Page) -> dict:
        """检测展示封面状态。

        返回:
          empty: 仍是「+」空上传框
          ready: 已出现真实封面预览
        注意：页面上其它图标/头像不能算封面。
        """
        try:
            state = await page.evaluate(
                """() => {
                    const isVis = (el) => {
                        if (!el) return false;
                        const r = el.getBoundingClientRect();
                        const s = getComputedStyle(el);
                        return r.width > 0 && r.height > 0
                            && s.visibility !== 'hidden'
                            && s.display !== 'none'
                            && Number(s.opacity || 1) > 0.05;
                    };
                    // 锚点：展示封面文案
                    let anchor = null;
                    const all = Array.from(document.querySelectorAll('div, span, label, section, p, li'));
                    for (const el of all) {
                        const t = (el.innerText || '').replace(/\\s+/g, '');
                        if (t === '展示封面' || t === '*展示封面' || (t.includes('展示封面') && t.length <= 12)) {
                            if (isVis(el)) { anchor = el; break; }
                        }
                    }
                    if (!anchor) {
                        return { empty: true, ready: false, reason: 'no-anchor' };
                    }
                    const ar = anchor.getBoundingClientRect();
                    // 封面控件通常在标签右侧/下方不远处
                    const inCoverZone = (r) => {
                        // 水平：标签附近到右侧一大片
                        if (r.right < ar.left - 20) return false;
                        if (r.left > ar.left + 700) return false;
                        // 垂直：标签附近上下 320px
                        if (r.bottom < ar.top - 40) return false;
                        if (r.top > ar.bottom + 320) return false;
                        return true;
                    };

                    // 1) 空状态：区域内还有明显的「+」上传框 / 提示文案
                    let hasPlusBox = false;
                    let hasTip = false;
                    for (const el of all) {
                        if (!isVis(el)) continue;
                        const r = el.getBoundingClientRect();
                        if (!inCoverZone(r)) continue;
                        const t = (el.innerText || '').replace(/\\s+/g, ' ').trim();
                        const compact = t.replace(/\\s+/g, '');
                        if (compact === '+' || compact === '＋') {
                            // 小方块更像上传入口
                            if (r.width >= 24 && r.width <= 220 && r.height >= 24 && r.height <= 220) {
                                hasPlusBox = true;
                            }
                        }
                        if (t.includes('优质的封面') || t.includes('格式支持JPEG') || t.includes('格式支持 JPEG')) {
                            hasTip = true;
                        }
                        // 虚线边框的空上传容器
                        const s = getComputedStyle(el);
                        const border = `${s.borderTopStyle} ${s.borderStyle}`;
                        if (border.includes('dashed') && r.width >= 60 && r.height >= 60 && r.width <= 240 && r.height <= 240) {
                            // 里面如果没有大图，视为空框
                            const img = el.querySelector('img');
                            if (!img) hasPlusBox = true;
                        }
                    }

                    // 2) 真实预览图：http/blob 图，尺寸像封面缩略图
                    let preview = null;
                    const imgs = Array.from(document.querySelectorAll('img'));
                    for (const img of imgs) {
                        if (!isVis(img)) continue;
                        const r = img.getBoundingClientRect();
                        if (!inCoverZone(r)) continue;
                        if (r.width < 50 || r.height < 50 || r.width > 360 || r.height > 360) continue;
                        const src = img.currentSrc || img.src || '';
                        if (!src) continue;
                        // 排除 svg 图标、超短 data uri 图标
                        if (src.startsWith('data:image/svg')) continue;
                        if (src.startsWith('data:') && src.length < 200) continue;
                        // 真实封面一般是 http(s)/blob，或较长 data:image
                        const looksReal = /^(https?:|blob:)/i.test(src) || (src.startsWith('data:image') && src.length > 500);
                        if (!looksReal) continue;
                        preview = { w: Math.round(r.width), h: Math.round(r.height), src: src.slice(0, 80) };
                        break;
                    }
                    // background-image 兜底
                    if (!preview) {
                        for (const el of all) {
                            if (!isVis(el)) continue;
                            const r = el.getBoundingClientRect();
                            if (!inCoverZone(r)) continue;
                            if (r.width < 50 || r.height < 50 || r.width > 360 || r.height > 360) continue;
                            const bg = getComputedStyle(el).backgroundImage || '';
                            if (!bg || bg === 'none' || !/url\\(/i.test(bg)) continue;
                            if (/svg|data:image\\/svg/i.test(bg)) continue;
                            if (!/https?:|blob:|data:image/i.test(bg)) continue;
                            preview = { w: Math.round(r.width), h: Math.round(r.height), src: bg.slice(0, 80) };
                            break;
                        }
                    }

                    // 只要空上传框还在，就绝不当作已上传
                    if (hasPlusBox) {
                        return { empty: true, ready: false, reason: 'plus-box', preview };
                    }
                    if (preview) {
                        return { empty: false, ready: true, reason: 'preview', preview };
                    }
                    // 没有预览；若还有提示文案，也算空
                    if (hasTip) {
                        return { empty: true, ready: false, reason: 'tip-only' };
                    }
                    return { empty: true, ready: false, reason: 'no-preview' };
                }"""
            )
            return state or {"empty": True, "ready": False, "reason": "eval-empty"}
        except Exception as exc:
            toutiao_logger.debug(f"封面状态检测失败: {exc}")
            return {"empty": True, "ready": False, "reason": "error"}

    async def _cover_already_set(self, page: Page, section=None) -> bool:
        """严格判断：仅当展示封面区已有真实预览，且不再是空「+」框。"""
        state = await self._cover_state(page)
        return bool(state.get("ready")) and not bool(state.get("empty"))

    async def _set_cover_via_file_chooser(self, page: Page, clickable, cover: Path) -> bool:
        """点击上传控件并用系统文件选择器塞文件。"""
        try:
            async with page.expect_file_chooser(timeout=5000) as fc_info:
                await clickable.click(timeout=3000, force=True)
            chooser = await fc_info.value
            await chooser.set_files(str(cover))
            await page.wait_for_timeout(1500)
            await self._confirm_cover_dialog(page)
            return True
        except Exception as exc:
            toutiao_logger.debug(f"file_chooser 上传失败: {exc}")
            return False

    async def _set_cover_via_input(self, page: Page, cover: Path, section=None) -> bool:
        """在封面区域内找 input[type=file] 直接 set_input_files。

        头条图文页封面区 class 常见：article-cover-add / article-cover-images
        很多情况下点击不会触发 filechooser，而是已有隐藏 input，直接 set 即可。
        """
        # 优先：封面专用区域附近的 input
        preferred_selectors = [
            '.article-cover-add input[type="file"]',
            '.article-cover-images input[type="file"]',
            '[class*="article-cover"] input[type="file"]',
            '[class*="cover-add"] input[type="file"]',
            'div:has-text("展示封面") input[type="file"]',
        ]
        scopes = []
        for sel in preferred_selectors:
            scopes.append(page.locator(sel))
        if section is not None:
            try:
                scopes.append(section.locator('input[type="file"]'))
            except Exception:
                pass
        scopes.append(page.locator('input[type="file"]'))

        seen = set()
        for scope in scopes:
            if scope is None:
                continue
            try:
                count = await scope.count()
            except Exception:
                continue
            for i in range(count):
                inp = scope.nth(i)
                try:
                    # 去重：同一 DOM 节点不重复 set
                    key = await inp.evaluate(
                        """el => {
                            const r = el.getBoundingClientRect();
                            return [el.accept||'', el.id||'', el.className||'', r.x, r.y].join('|');
                        }"""
                    )
                    if key in seen:
                        continue
                    seen.add(key)

                    accept = ((await inp.get_attribute("accept")) or "").lower()
                    if accept and "video" in accept and "image" not in accept:
                        continue
                    if accept and "image" not in accept and accept not in ("", "*/*", "image/*"):
                        if not any(x in accept for x in ("png", "jpg", "jpeg", ".png", ".jpg")):
                            continue

                    await inp.set_input_files(str(cover))
                    toutiao_logger.info(f"已向封面 input 写入文件: {cover.name} accept={accept or '*'}")
                    await page.wait_for_timeout(1600)
                    await self._confirm_cover_dialog(page)
                    for wait_i in range(12):
                        st = await self._cover_state(page)
                        if st.get("ready") and not st.get("empty"):
                            return True
                        if wait_i in (0, 4, 8):
                            toutiao_logger.info(
                                f"等待封面预览... empty={st.get('empty')} reason={st.get('reason')}"
                            )
                        await page.wait_for_timeout(400)
                    # 再确认一次裁剪弹窗
                    await self._confirm_cover_dialog(page)
                    st = await self._cover_state(page)
                    if st.get("ready") and not st.get("empty"):
                        return True
                except Exception as exc:
                    toutiao_logger.debug(f"set_input_files[{i}] 失败: {exc}")
                    continue
        return False

    async def _set_cover_via_article_cover_add(self, page: Page, cover: Path) -> bool:
        """针对头条 class=article-cover-add 的专用上传路径。"""
        try:
            add_box = page.locator('.article-cover-add, [class*="article-cover-add"]').first
            if not await add_box.count():
                return False

            # 1) 盒子内部/相邻隐藏 input
            for sel in (
                '.article-cover-add input[type="file"]',
                '.article-cover-images input[type="file"]',
                '[class*="article-cover"] input[type="file"]',
            ):
                loc = page.locator(sel)
                n = await loc.count()
                for i in range(n):
                    inp = loc.nth(i)
                    try:
                        await inp.set_input_files(str(cover))
                        toutiao_logger.info(f"article-cover 路径写入封面: {cover.name}")
                        await page.wait_for_timeout(1800)
                        await self._confirm_cover_dialog(page)
                        for _ in range(12):
                            st = await self._cover_state(page)
                            if st.get("ready") and not st.get("empty"):
                                return True
                            await page.wait_for_timeout(400)
                    except Exception:
                        continue

            # 2) 点击 add 盒；若弹出 filechooser 则用，否则再扫 input
            try:
                async with page.expect_file_chooser(timeout=2500) as fc_info:
                    await add_box.click(timeout=2500, force=True)
                chooser = await fc_info.value
                await chooser.set_files(str(cover))
                toutiao_logger.info(f"article-cover-add filechooser 选中: {cover.name}")
                await page.wait_for_timeout(1800)
                await self._confirm_cover_dialog(page)
                for _ in range(12):
                    st = await self._cover_state(page)
                    if st.get("ready") and not st.get("empty"):
                        return True
                    await page.wait_for_timeout(400)
            except Exception:
                # 点击后可能动态插入 input
                await page.wait_for_timeout(500)
                if await self._set_cover_via_input(page, cover, None):
                    return True
            return False
        except Exception as exc:
            toutiao_logger.debug(f"article-cover-add 路径失败: {exc}")
            return False

    async def _screenshot_cover_debug(self, page: Page) -> None:
        try:
            path = Path(self.account_file).with_name("toutiao_cover_fail.png")
            await page.screenshot(path=str(path), full_page=True)
            toutiao_logger.warning(f"封面失败截图: {path}")
        except Exception:
            pass

    async def apply_work_statements(self, page: Page) -> None:
        """在封面下方勾选「作品声明」（单选）。

        页面常见选项：
          取材网络 / 引用站内 / 个人观点，仅供参考 / 引用AI /
          虚构演绎，故事经历 / 投资观点，仅供参考 / 健康医疗分享，仅供参考
        未选择时跳过。
        """
        statements = list(self.work_statements or [])[:1]
        if not statements:
            toutiao_logger.info("未配置作品声明，跳过")
            return

        toutiao_logger.info(f"开始设置作品声明（单选）: {statements[0]}")
        try:
            # 滚到作品声明区域
            scrolled = False
            for label in ("作品声明", "取材网络", "引用站内"):
                try:
                    loc = page.get_by_text(label, exact=False).first
                    if await loc.count() and await loc.is_visible():
                        await loc.scroll_into_view_if_needed(timeout=3000)
                        scrolled = True
                        break
                except Exception:
                    continue
            if not scrolled:
                try:
                    await page.evaluate(
                        "window.scrollTo(0, Math.max(document.body.scrollHeight * 0.55, 800))"
                    )
                except Exception:
                    pass
            await page.wait_for_timeout(400)

            # 优先在「作品声明」附近找 checkbox 区域，避免误点其它声明
            section = None
            for sel in (
                'div:has-text("作品声明"):has-text("取材网络")',
                'div:has-text("作品声明"):has-text("引用站内")',
                'section:has-text("作品声明")',
                'div:has-text("作品声明")',
            ):
                try:
                    loc = page.locator(sel)
                    count = await loc.count()
                    best = None
                    best_h = 10**9
                    for i in range(min(count, 10)):
                        item = loc.nth(i)
                        box = await item.bounding_box()
                        if not box:
                            continue
                        h = box.get("height") or 0
                        w = box.get("width") or 0
                        if 40 < h < 420 and w > 200 and h < best_h:
                            best = item
                            best_h = h
                    if best is not None:
                        section = best
                        break
                except Exception:
                    continue

            async def _checkbox_already_checked(target) -> bool:
                try:
                    # input[type=checkbox]
                    inp = target.locator('input[type="checkbox"]').first
                    if await inp.count():
                        return bool(await inp.is_checked())
                except Exception:
                    pass
                try:
                    cls = (await target.get_attribute("class")) or ""
                    if "checked" in cls or "is-checked" in cls or "selected" in cls:
                        return True
                    parent = target.locator("xpath=ancestor-or-self::*[contains(@class,'checked') or contains(@class,'selected')][1]")
                    if await parent.count():
                        return True
                except Exception:
                    pass
                return False

            async def _click_statement(label: str) -> bool:
                scopes = []
                if section is not None:
                    scopes.append(section)
                scopes.append(page)

                candidates = []
                for scope in scopes:
                    try:
                        candidates.extend(
                            [
                                scope.get_by_label(label, exact=True),
                                scope.locator(f'label:has-text("{label}")'),
                                scope.get_by_text(label, exact=True),
                                scope.locator(f'span:has-text("{label}")'),
                                scope.locator(f'div:has-text("{label}")'),
                            ]
                        )
                    except Exception:
                        continue

                for loc in candidates:
                    try:
                        count = await loc.count()
                    except Exception:
                        continue
                    for i in range(min(count, 6)):
                        item = loc.nth(i)
                        try:
                            if not await item.is_visible():
                                continue
                            # 过滤掉整块大容器：只点短文本节点
                            box = await item.bounding_box()
                            if box and (box.get("height") or 0) > 80:
                                continue
                            text = ""
                            try:
                                text = ((await item.inner_text()) or "").strip().replace("\n", " ")
                            except Exception:
                                pass
                            if text and label not in text:
                                continue
                            # 若文案过长（整块区域），跳过
                            if text and len(text) > max(len(label) + 12, 40):
                                continue

                            if await _checkbox_already_checked(item):
                                toutiao_logger.info(f"作品声明已勾选: {label}")
                                return True

                            # 优先点 label 内的 input / 自身
                            clicked = False
                            try:
                                cb = item.locator('input[type="checkbox"]').first
                                if await cb.count():
                                    try:
                                        await cb.check(force=True, timeout=2000)
                                    except Exception:
                                        await cb.click(force=True, timeout=2000)
                                    clicked = True
                            except Exception:
                                pass
                            if not clicked:
                                await item.click(timeout=2500, force=True)
                                clicked = True
                            await page.wait_for_timeout(350)

                            if await _checkbox_already_checked(item):
                                toutiao_logger.info(f"已勾选作品声明: {label}")
                                return True
                            # 有的 UI 点文字后 class 变化不明显，只要点过就算成功
                            if clicked:
                                toutiao_logger.info(f"已点击作品声明: {label}")
                                return True
                        except Exception:
                            continue
                return False

            added = []
            failed = []
            for label in statements:
                ok = await _click_statement(label)
                if ok:
                    added.append(label)
                else:
                    failed.append(label)

            if added:
                toutiao_logger.success(f"作品声明已设置: {added}")
            if failed:
                await self._screenshot_work_statement_debug(page)
                toutiao_logger.warning(f"未能勾选的作品声明: {failed}")
            if not added:
                toutiao_logger.warning("未成功勾选任何作品声明，请 dry_run 人工确认页面结构")
        except Exception as exc:
            toutiao_logger.warning(f"作品声明设置失败（可忽略）: {exc}")
            await self._screenshot_work_statement_debug(page)

    async def _screenshot_work_statement_debug(self, page: Page) -> None:
        try:
            path = Path(self.account_file).with_name("toutiao_work_statement_fail.png")
            await page.screenshot(path=str(path), full_page=True)
            toutiao_logger.warning(f"作品声明失败截图: {path}")
        except Exception:
            pass

    async def handle_cover(self, page: Page) -> None:
        """图文展示封面：优先「单图」本地上传（JPEG/PNG，单张最大 20MB）。"""
        if not self.cover_path:
            toutiao_logger.info("未提供封面，跳过封面设置（页面可走无封面）")
            return
        cover = Path(str(self.cover_path))
        if not cover.exists():
            toutiao_logger.warning(f"封面文件不存在，跳过: {cover}")
            return
        size = cover.stat().st_size
        if size > 20 * 1024 * 1024:
            toutiao_logger.warning(f"封面超过 20MB，跳过: {cover} ({size} bytes)")
            return
        if cover.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}:
            toutiao_logger.warning(f"封面格式可能不受支持（建议 JPEG/PNG）: {cover.suffix}")

        toutiao_logger.info(f"开始上传展示封面: {cover} ({size} bytes)")
        try:
            try:
                await page.get_by_text("展示封面", exact=False).first.scroll_into_view_if_needed(timeout=3000)
            except Exception:
                await page.evaluate("window.scrollTo(0, Math.max(document.body.scrollHeight * 0.45, 600))")
            await page.wait_for_timeout(400)

            section = await self._find_cover_section(page)

            # 选择「单图」
            single_clicked = False
            single_candidates = []
            if section is not None and hasattr(section, "locator"):
                single_candidates.extend(
                    [
                        section.get_by_text("单图", exact=True),
                        section.locator('label:has-text("单图")'),
                    ]
                )
            single_candidates.extend(
                [
                    page.get_by_text("单图", exact=True),
                    page.locator('label:has-text("单图")'),
                ]
            )
            for loc in single_candidates:
                try:
                    target = loc.first
                    if await target.count() and await target.is_visible():
                        await target.click(timeout=2000)
                        single_clicked = True
                        await page.wait_for_timeout(400)
                        toutiao_logger.info("已选择封面模式: 单图")
                        break
                except Exception:
                    continue
            if not single_clicked:
                toutiao_logger.warning("未点到「单图」单选，继续尝试上传")

            pre_state = await self._cover_state(page)
            toutiao_logger.info(
                f"上传前封面状态: empty={pre_state.get('empty')} ready={pre_state.get('ready')} reason={pre_state.get('reason')}"
            )
            if pre_state.get("ready") and not pre_state.get("empty"):
                toutiao_logger.info("展示封面已是真实预览图，跳过重复上传")
                return

            # 策略优先序（基于实测）：
            # 1) article-cover-add 专用路径 / 隐藏 input 直接 set
            # 2) 通用 input set
            # 3) 坐标点击 + 短超时 filechooser（兜底）
            if await self._set_cover_via_article_cover_add(page, cover):
                toutiao_logger.success(f"已上传封面: {cover.name}")
                return

            if await self._set_cover_via_input(page, cover, section):
                toutiao_logger.success(f"已上传封面: {cover.name}")
                return

            # 兜底：找 article-cover / 虚线 + 框坐标，短等 filechooser
            try:
                plus_info = await page.evaluate(
                    """() => {
                        const isVis = (el) => {
                            const r = el.getBoundingClientRect();
                            const s = getComputedStyle(el);
                            return r.width >= 36 && r.height >= 36 && r.width <= 260 && r.height <= 260
                                && s.visibility !== 'hidden' && s.display !== 'none' && Number(s.opacity||1) > 0.1;
                        };
                        const nodes = Array.from(document.querySelectorAll('div, span, i, button, label, section'));
                        let anchorTop = 0;
                        for (const n of nodes) {
                            const t = (n.innerText || '').trim();
                            if (t === '展示封面' || (t.includes('展示封面') && t.length < 20)) {
                                const r = n.getBoundingClientRect();
                                if (r.width > 0) { anchorTop = r.top; break; }
                            }
                        }
                        const cands = [];
                        for (const el of nodes) {
                            if (!isVis(el)) continue;
                            const r = el.getBoundingClientRect();
                            if (anchorTop && (r.top < anchorTop - 20 || r.top > anchorTop + 280)) continue;
                            const t = (el.innerText || '').replace(/\\s+/g, '');
                            const cls = String(el.className || '');
                            let score = 0;
                            if (/article-cover-add/i.test(cls)) score += 20;
                            if (/article-cover/i.test(cls)) score += 10;
                            if (t === '+' || t.includes('+')) score += 8;
                            if (/upload|cover|plus|dashed|empty/i.test(cls)) score += 6;
                            if ((getComputedStyle(el).borderStyle || '').includes('dashed')) score += 5;
                            if (score >= 10) {
                                cands.push({x: r.left + r.width/2, y: r.top + r.height/2, score, cls: cls.slice(0,40)});
                            }
                        }
                        cands.sort((a,b) => b.score - a.score);
                        return cands.slice(0, 3);
                    }"""
                )
            except Exception:
                plus_info = []

            for info in plus_info or []:
                x, y = info.get("x"), info.get("y")
                if x is None or y is None:
                    continue
                toutiao_logger.info(
                    f"兜底点击封面框 @({int(x)},{int(y)}) score={info.get('score')} cls={info.get('cls')!r}"
                )
                try:
                    async with page.expect_file_chooser(timeout=2500) as fc_info:
                        await page.mouse.click(float(x), float(y))
                    chooser = await fc_info.value
                    await chooser.set_files(str(cover))
                    await page.wait_for_timeout(1800)
                    await self._confirm_cover_dialog(page)
                    st = await self._cover_state(page)
                    if st.get("ready") and not st.get("empty"):
                        toutiao_logger.success(f"已上传封面: {cover.name}")
                        return
                except Exception:
                    # 点击后可能露出 input
                    if await self._set_cover_via_input(page, cover, section):
                        toutiao_logger.success(f"已上传封面: {cover.name}")
                        return

            await self._screenshot_cover_debug(page)
            try:
                dump = await page.evaluate(
                    """() => Array.from(document.querySelectorAll('input[type=file]')).map((el, i) => ({
                        i,
                        accept: el.getAttribute('accept'),
                        cls: String(el.className || '').slice(0, 60),
                        id: el.id || '',
                        hidden: el.hidden || getComputedStyle(el).display === 'none',
                    }))"""
                )
                toutiao_logger.warning(f"未找到可用的封面上传入口；页面 file input: {dump}")
            except Exception:
                toutiao_logger.warning("未找到可用的封面上传入口，请 dry_run 人工确认页面结构")
        except Exception as exc:
            toutiao_logger.warning(f"封面设置失败（可忽略）: {exc}")
            await self._screenshot_cover_debug(page)

    async def set_schedule_time(self, page: Page, publish_date: datetime) -> None:
        try:
            schedule_toggle = page.locator("text=定时发布").first
            if await schedule_toggle.count():
                await schedule_toggle.click(timeout=3000)
                await page.wait_for_timeout(800)
            date_str = publish_date.strftime("%Y-%m-%d %H:%M")
            time_input = page.locator(
                'input[placeholder*="时间"], input[placeholder*="选择"], input[type="text"][class*="date"]'
            ).first
            if await time_input.count():
                await time_input.click(force=True)
                await time_input.fill(date_str)
                await page.keyboard.press("Enter")
                toutiao_logger.info(f"已设置定时: {date_str}")
            else:
                toutiao_logger.warning("未找到定时时间输入框，将按立即发布处理")
        except Exception as exc:
            toutiao_logger.warning(f"定时设置失败: {exc}")

    async def publish(self, page: Page) -> None:
        await _dismiss_overlays(page)
        if self.publish_date != 0 and isinstance(self.publish_date, datetime):
            await self.set_schedule_time(page, self.publish_date)

        candidates = [
            page.get_by_role("button", name="发布", exact=True),
            page.locator('button:has-text("发布")').filter(has_not_text="定时").last,
            page.locator('button:has-text("发布")').last,
            page.get_by_text("发布", exact=True).last,
        ]
        clicked = False
        for btn in candidates:
            try:
                if not await btn.count():
                    continue
                target = btn.first if hasattr(btn, "first") else btn
                if not await target.is_visible():
                    continue
                await target.scroll_into_view_if_needed()
                await page.wait_for_timeout(300)
                try:
                    await target.click(timeout=5000)
                except Exception:
                    await target.click(force=True, timeout=5000)
                clicked = True
                break
            except Exception:
                continue

        if not clicked:
            clicked = await page.evaluate(
                """() => {
                    const buttons = Array.from(document.querySelectorAll('button, [role="button"]'));
                    const match = buttons.find(el => {
                        const t = (el.innerText || el.textContent || '').trim();
                        return t === '发布' && !el.disabled;
                    });
                    if (!match) return false;
                    match.click();
                    return true;
                }"""
            )
        if not clicked:
            raise RuntimeError("未找到可点击的「发布」按钮")
        await page.wait_for_timeout(3000)
        toutiao_logger.success("已点击文章发布")

    async def upload(self, playwright: Playwright) -> None:
        if not (self.body or "").strip() and not self.tags:
            raise ValueError("文章正文不能为空")
        if not self.title:
            raise ValueError("文章标题不能为空")

        launch_kwargs = _build_launch_kwargs(self.headless)
        browser = await playwright.chromium.launch(**launch_kwargs)
        context = await browser.new_context(
            storage_state=f"{self.account_file}",
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

        article_urls = [
            TOUTIAO_ARTICLE_URL,
            "https://mp.toutiao.com/profile_v4/graphic/publish?from=menu",
            "https://mp.toutiao.com/profile_v4/graphic/articles/editor",
        ]
        opened = False
        for url in article_urls:
            try:
                toutiao_logger.info(f"正在打开今日头条图文发布页... {url}")
                await page.goto(url, timeout=60000)
                await page.wait_for_timeout(2500)
                await _dismiss_overlays(page)
                if TOUTIAO_LOGIN_PATH in page.url or "sso.toutiao.com" in page.url:
                    raise RuntimeError("今日头条 cookie 已失效，请重新登录")
                _frame, editor = await self._find_editor(page)
                title_ok = await page.locator(
                    'input[placeholder*="标题"], input[placeholder*="字符"], textarea[placeholder*="标题"]'
                ).count()
                if editor or title_ok:
                    opened = True
                    break
            except RuntimeError:
                raise
            except Exception as exc:
                toutiao_logger.warning(f"打开 {url} 失败: {exc}")
        if not opened:
            raise RuntimeError("无法打开今日头条图文发布页，请检查账号权限或页面改版")

        await self.fill_title(page)
        await page.wait_for_timeout(500)
        await self.fill_body(page)
        await self.handle_cover(page)
        await self.apply_work_statements(page)
        await _dismiss_overlays(page)

        if self.dry_run:
            toutiao_logger.warning("🛑 【仅预览不发布】已跳过点击发布按钮")
            toutiao_logger.info(
                "👀 请在浏览器窗口核对：标题、正文、文末话题标签（非纯文本 #）、展示封面、以及作品声明"
            )
            try:
                await page.screenshot(
                    full_page=True,
                    path=str(Path(self.account_file).with_name("toutiao_article_dry_run_preview.png")),
                )
            except Exception:
                pass
            for _ in range(120):
                await asyncio.sleep(1)
            toutiao_logger.info("🛑 预览结束，关闭浏览器（未点击发布）")
        else:
            await self.publish(page)
            await page.wait_for_timeout(3000)
            toutiao_logger.success("文章发布流程完成")

        await context.storage_state(path=self.account_file)
        toutiao_logger.info("cookie 更新完毕")
        await asyncio.sleep(1)
        await context.close()
        await browser.close()

    async def main(self):
        async with async_playwright() as playwright:
            await self.upload(playwright)
