# -*- coding: utf-8 -*-
"""知乎文章发布（Playwright）。第一期仅文章。"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime
from pathlib import Path

from playwright.async_api import Page, async_playwright

from conf import LOCAL_CHROME_HEADLESS, LOCAL_CHROME_PATH
from utils.base_social_media import set_init_script
from utils.log import zhihu_logger

ZHIHU_LOGIN_URL = "https://www.zhihu.com/signin"
ZHIHU_WRITE_URL = "https://zhuanlan.zhihu.com/write"
ZHIHU_CREATOR_URL = "https://www.zhihu.com/creator"
TITLE_MAX_LEN = 100
COVER_MAX_BYTES = 10 * 1024 * 1024
COVER_EXTS = {".jpg", ".jpeg", ".png"}

# 知乎写文章页「创作声明」下拉选项
ZHIHU_CREATION_STATEMENT_OPTIONS = (
    "包含剧透",
    "包含医疗建议",
    "虚构创作",
    "包含理财内容",
    "包含 AI 辅助创作 作者对内容负责",
    "无声明",
)
ZHIHU_CREATION_STATEMENT_DEFAULT = "无声明"


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


def _is_login_url(url: str) -> bool:
    u = (url or "").lower()
    return any(k in u for k in ("/signin", "/login", "passport", "account/login"))


async def _has_auth_cookie(context) -> bool:
    """知乎登录成功后会有 z_c0。"""
    try:
        cookies = await context.cookies()
    except Exception:
        return False
    return any(c.get("name") == "z_c0" for c in cookies)


async def _wait_until_logged_in(page: Page, context, timeout_ms: int = 200_000) -> bool:
    """等待人工登录完成（优先检测 z_c0）。"""
    elapsed = 0
    step = 1000
    while elapsed < timeout_ms:
        if await _has_auth_cookie(context):
            return True
        if (not _is_login_url(page.url)) and ("zhihu.com" in (page.url or "")):
            # 已离开登录页时再确认一次 cookie
            await page.wait_for_timeout(500)
            if await _has_auth_cookie(context):
                return True
        await page.wait_for_timeout(step)
        elapsed += step
    return await _has_auth_cookie(context)


async def cookie_auth(account_file) -> bool:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(**_build_launch_kwargs(headless=LOCAL_CHROME_HEADLESS))
        try:
            context = await browser.new_context(storage_state=account_file)
            context = await set_init_script(context)
            page = await context.new_page()
            await page.goto(ZHIHU_WRITE_URL, timeout=60000)
            await page.wait_for_timeout(3000)
            if _is_login_url(page.url):
                zhihu_logger.error("[+] 知乎 cookie 失效")
                return False
            # 写文章页或创作中心标记
            markers = [
                'textarea[placeholder*="标题"]',
                'input[placeholder*="标题"]',
                'text=发布',
                'text=写文章',
            ]
            for sel in markers:
                try:
                    if await page.locator(sel).count():
                        zhihu_logger.success("[+] 知乎 cookie 有效")
                        return True
                except Exception:
                    continue
            if "zhihu.com" in page.url and not _is_login_url(page.url):
                zhihu_logger.success("[+] 知乎 cookie 有效（域名已登录）")
                return True
            zhihu_logger.error("[+] 知乎 cookie 失效")
            return False
        except Exception as exc:
            zhihu_logger.warning(f"[+] cookie 校验异常，按失效处理: {exc}")
            return False
        finally:
            await browser.close()


async def zhihu_cookie_gen(account_file):
    """CLI/本地调试：打开登录页，手动登录后保存 cookie。"""
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(**_build_launch_kwargs(headless=False))
        context = await browser.new_context()
        context = await set_init_script(context)
        page = await context.new_page()
        await page.goto(ZHIHU_LOGIN_URL, timeout=60000)
        zhihu_logger.info("请在浏览器中完成知乎登录；检测到登录凭证 z_c0 后会自动保存…")
        ok = await _wait_until_logged_in(page, context, timeout_ms=200_000)
        if not ok:
            await context.close()
            await browser.close()
            raise RuntimeError("知乎登录超时：未检测到登录凭证 z_c0，请重新登录")
        Path(account_file).parent.mkdir(parents=True, exist_ok=True)
        await context.storage_state(path=account_file)
        zhihu_logger.success(f"cookie saved: {account_file}")
        await context.close()
        await browser.close()


async def zhihu_setup(account_file, handle=False):
    if not os.path.exists(account_file) or not await cookie_auth(account_file):
        if not handle:
            return False
        zhihu_logger.error("cookie文件不存在或已失效，即将打开浏览器，请手动登录知乎")
        await zhihu_cookie_gen(account_file)
    return True


class ZhiHuArticle(object):
    """知乎文章发布。"""

    def __init__(
        self,
        title,
        body,
        tags,
        publish_date: datetime | int,
        account_file,
        dry_run=False,
        cover_path=None,
        creation_statement=None,
    ):
        self.title = (title or "").strip()[:TITLE_MAX_LEN]
        if not self.title:
            raise ValueError("知乎文章标题不能为空")
        self.body = (body or "").strip()
        if not self.body:
            raise ValueError("知乎文章正文不能为空")
        self.tags = tags or []
        self.publish_date = publish_date
        self.account_file = account_file
        self.dry_run = bool(dry_run)
        self.headless = LOCAL_CHROME_HEADLESS if not self.dry_run else False
        self.cover_path = self._normalize_cover(cover_path)
        self.creation_statement = self._normalize_creation_statement(creation_statement)

    @staticmethod
    def _normalize_cover(cover_path) -> str | None:
        if not cover_path or not str(cover_path).strip():
            return None
        p = Path(str(cover_path).strip())
        if not p.is_file():
            zhihu_logger.warning(f"封面不存在，将跳过: {p}")
            return None
        if p.suffix.lower() not in COVER_EXTS:
            zhihu_logger.warning(f"封面格式不支持（需 jpg/jpeg/png），将跳过: {p}")
            return None
        if p.stat().st_size > COVER_MAX_BYTES:
            zhihu_logger.warning(f"封面超过 10MB，将跳过: {p}")
            return None
        return str(p.resolve())

    @staticmethod
    def _normalize_creation_statement(creation_statement) -> str:
        if creation_statement is None or creation_statement == "":
            return ZHIHU_CREATION_STATEMENT_DEFAULT
        if isinstance(creation_statement, (list, tuple)):
            raw = next((str(x).strip() for x in creation_statement if str(x).strip()), "")
        else:
            raw = str(creation_statement).strip()
        if not raw:
            return ZHIHU_CREATION_STATEMENT_DEFAULT

        aliases = {
            "无": "无声明",
            "无特别声明": "无声明",
            "剧透": "包含剧透",
            "医疗": "包含医疗建议",
            "医疗建议": "包含医疗建议",
            "虚构": "虚构创作",
            "理财": "包含理财内容",
            "理财内容": "包含理财内容",
            "ai": "包含 AI 辅助创作 作者对内容负责",
            "AI": "包含 AI 辅助创作 作者对内容负责",
            "AI辅助": "包含 AI 辅助创作 作者对内容负责",
            "包含AI辅助创作": "包含 AI 辅助创作 作者对内容负责",
            "包含 AI 辅助创作": "包含 AI 辅助创作 作者对内容负责",
        }
        text = aliases.get(raw, aliases.get(raw.lower(), raw))
        if text in ZHIHU_CREATION_STATEMENT_OPTIONS:
            return text
        matched = next(
            (opt for opt in ZHIHU_CREATION_STATEMENT_OPTIONS if opt.startswith(text) or text in opt),
            None,
        )
        if matched:
            return matched
        zhihu_logger.warning(f"未知创作声明「{raw}」，回退为「{ZHIHU_CREATION_STATEMENT_DEFAULT}」")
        return ZHIHU_CREATION_STATEMENT_DEFAULT

    async def upload(self, playwright) -> None:
        browser = await playwright.chromium.launch(**_build_launch_kwargs(headless=self.headless))
        context = await browser.new_context(storage_state=str(self.account_file))
        context = await set_init_script(context)
        page = await context.new_page()
        try:
            await page.goto(ZHIHU_WRITE_URL, timeout=90000, wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)
            if _is_login_url(page.url):
                raise RuntimeError("知乎 cookie 已失效，请重新登录")
            await self.fill_title(page)
            await self.fill_body(page)
            if self.cover_path:
                await self.upload_cover(page)
            await self.apply_creation_statement(page)
            if self.dry_run:
                zhihu_logger.warning("🛑 【仅预览不发布】已跳过点击发布按钮")
                zhihu_logger.info("👀 请在浏览器窗口核对：标题、正文、封面、创作声明")
                zhihu_logger.info("⏳ 页面将保持打开约 120 秒后自动关闭（也可手动关浏览器）")
                try:
                    preview = Path(self.account_file).with_name("zhihu_article_dry_run_preview.png")
                    await page.screenshot(full_page=True, path=str(preview))
                    zhihu_logger.info(f"📸 预览截图已保存: {preview}")
                except Exception as exc:
                    zhihu_logger.debug(f"预览截图失败: {exc}")
                for i in range(120):
                    await asyncio.sleep(1)
                    if i in (30, 60, 90):
                        zhihu_logger.info(f"⏳ 预览中…还剩约 {120 - i} 秒自动关闭")
                zhihu_logger.info("🛑 预览结束，关闭浏览器（未点击发布）")
                return
            await self.click_publish(page)
            zhihu_logger.success("知乎文章发布流程已完成点击发布")
        finally:
            await context.close()
            await browser.close()

    async def apply_creation_statement(self, page: Page) -> None:
        """选择写文章页「创作声明」下拉项。"""
        label = self.creation_statement or ZHIHU_CREATION_STATEMENT_DEFAULT
        try:
            # 创作声明在编辑区下方，先滚入视口
            for _ in range(10):
                if await page.locator('label:has-text("创作声明")').count():
                    break
                await page.mouse.wheel(0, 500)
                await page.wait_for_timeout(200)

            row = page.locator('div:has(> label:has-text("创作声明"))').first
            if not await row.count():
                zhihu_logger.warning("未找到创作声明区域，请 dry_run 人工确认")
                return

            combo = row.locator('button[role="combobox"], button.Select-button').first
            if not await combo.count():
                zhihu_logger.warning("未找到创作声明下拉按钮，请 dry_run 人工确认")
                return

            await combo.scroll_into_view_if_needed()
            current = ((await combo.inner_text()) or "").strip().replace("\n", " ")
            if current == label:
                zhihu_logger.info(f"创作声明已是「{label}」")
                return

            await combo.click(timeout=5000)
            await page.wait_for_timeout(500)

            # 选项在 Popover 中：button.Select-option[role=option]
            option = page.get_by_role("option", name=label, exact=True).first
            if not await option.count():
                option = page.locator(f'button.Select-option[role="option"]').filter(has_text=label).first
            if not await option.count():
                # 再试一次打开
                await combo.click(timeout=3000, force=True)
                await page.wait_for_timeout(600)
                option = page.get_by_role("option", name=label, exact=True).first

            if not await option.count():
                zhihu_logger.warning(f"下拉中未找到创作声明选项「{label}」")
                try:
                    await page.keyboard.press("Escape")
                except Exception:
                    pass
                return

            await option.click(timeout=5000)
            await page.wait_for_timeout(400)

            after = ((await combo.inner_text()) or "").strip().replace("\n", " ")
            if after == label or label in after:
                zhihu_logger.success(f"已选择创作声明: {label}")
            else:
                zhihu_logger.warning(f"创作声明点击后显示为「{after}」，期望「{label}」")
        except Exception as exc:
            zhihu_logger.warning(f"设置创作声明失败（可忽略）: {exc}")

    async def fill_title(self, page: Page) -> None:
        candidates = [
            page.locator('textarea[placeholder*="标题"]').first,
            page.locator('input[placeholder*="标题"]').first,
            page.get_by_placeholder("请输入标题").first,
            page.locator('[class*="WriteIndex"] textarea').first,
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
            raise RuntimeError("未找到知乎文章标题输入框")
        await title_field.click(force=True)
        await title_field.fill("")
        await title_field.fill(self.title)
        zhihu_logger.info(f"已填写文章标题: {self.title}")

    async def fill_body(self, page: Page) -> None:
        selectors = [
            ".public-DraftEditor-content",
            '[contenteditable="true"]',
            ".ProseMirror",
            'div[role="textbox"]',
            ".ql-editor",
        ]
        editor = None
        for sel in selectors:
            loc = page.locator(sel).first
            try:
                if await loc.count() and await loc.is_visible():
                    editor = loc
                    break
            except Exception:
                continue
        if not editor:
            raise RuntimeError("未找到知乎文章正文编辑器")
        await editor.click(force=True)
        await page.wait_for_timeout(200)
        try:
            await page.context.grant_permissions(["clipboard-read", "clipboard-write"])
        except Exception:
            pass
        await page.keyboard.press("Control+A")
        await page.keyboard.press("Backspace")
        try:
            await page.evaluate(
                """async (t) => { await navigator.clipboard.writeText(t); }""",
                self.body,
            )
            await page.keyboard.press("Control+V")
        except Exception:
            for para in self.body.split("\n"):
                await page.keyboard.type(para, delay=10)
                await page.keyboard.press("Enter")
        zhihu_logger.info(f"已填写正文，长度={len(self.body)}")

    async def upload_cover(self, page: Page) -> None:
        # 多候选：封面入口文案/上传 input；实现时以真实页面为准微调
        openers = [
            'text=添加封面',
            'text=设置封面',
            'text=文章封面',
            'button:has-text("封面")',
        ]
        for sel in openers:
            try:
                loc = page.locator(sel).first
                if await loc.count() and await loc.is_visible():
                    await loc.click(timeout=3000)
                    await page.wait_for_timeout(500)
                    break
            except Exception:
                continue
        file_input = page.locator('input[type="file"]').last
        if not await file_input.count():
            zhihu_logger.warning("未找到封面文件选择框，跳过封面")
            return
        await file_input.set_input_files(self.cover_path)
        await page.wait_for_timeout(1500)
        for confirm in ('button:has-text("确定")', 'button:has-text("完成")', 'button:has-text("确认")'):
            try:
                btn = page.locator(confirm).first
                if await btn.count() and await btn.is_visible():
                    await btn.click(timeout=2000)
                    break
            except Exception:
                continue
        zhihu_logger.info(f"已尝试上传封面: {self.cover_path}")

    async def click_publish(self, page: Page) -> None:
        candidates = [
            page.get_by_role("button", name="发布").first,
            page.locator('button:has-text("发布")').first,
        ]
        for loc in candidates:
            try:
                if await loc.count() and await loc.is_visible():
                    await loc.click(timeout=5000)
                    await page.wait_for_timeout(3000)
                    # 二次确认弹窗
                    for confirm in ('button:has-text("确定")', 'button:has-text("确认发布")'):
                        try:
                            c = page.locator(confirm).first
                            if await c.count() and await c.is_visible():
                                await c.click(timeout=3000)
                                await page.wait_for_timeout(2000)
                        except Exception:
                            pass
                    return
            except Exception:
                continue
        raise RuntimeError("未找到知乎发布按钮")

    async def main(self):
        async with async_playwright() as playwright:
            await self.upload(playwright)
