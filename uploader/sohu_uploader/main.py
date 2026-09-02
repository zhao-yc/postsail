# -*- coding: utf-8 -*-
"""搜狐号图文文章发布（Playwright）。

第一期仅支持文章，不支持视频。
发布页以 mp.sohu.com 创作者后台为准，选择器做多候选兜底。
"""
from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime
from pathlib import Path

from playwright.async_api import Page, Playwright, async_playwright

from conf import LOCAL_CHROME_HEADLESS, LOCAL_CHROME_PATH
from utils.log import sohu_logger


async def _prepare_context(context):
    """搜狐号发文页是 qiankun 微前端，不能注入 stealth.min.js。

    stealth 会改写 document.createElement，导致 micro-app 报错：
    application 'contentManagement*' died in status LOADING_SOURCE_CODE
    （createElement proxy 不匹配），页面一直停在「加载中...」。
    """
    return context

SOHU_HOME_URL = "https://mp.sohu.com/"
SOHU_LOGIN_URL = "https://mp.sohu.com/mpfe/v4/login"
SOHU_CONTENT_LIST_URL = "https://mp.sohu.com/mpfe/v3/main/content/list"
SOHU_FIRST_PAGE_URL = "https://mp.sohu.com/mpfe/v4/contentManagement/first/page"
SOHU_ARTICLE_URLS = [
    "https://mp.sohu.com/mpfe/v4/contentManagement/news/addarticle",
    "https://mp.sohu.com/mpfe/v4/contentManagement/news/addarticle?contentStatus=1",
    "https://mp.sohu.com/mpfe/v3/main/news/addarticle?type=news",
    "https://mp.sohu.com/mpfe/v3/main/news/addarticle",
]

TITLE_INPUT_SELECTOR = (
    'input[placeholder*="标题"], textarea[placeholder*="标题"], '
    'input[placeholder*="请输入标题"], input[placeholder*="文章标题"], '
    'input[name="title"], .publish-title input, input[class*="title"]'
)

# 搜狐号发文页「信息来源」单选选项
SOHU_INFO_SOURCE_OPTIONS = (
    "无特别声明",
    "引用声明",
    "包含AI创作内容",
    "包含虚构创作",
)
SOHU_INFO_SOURCE_DEFAULT = "无特别声明"


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
    return any(
        key in u
        for key in (
            "/login",
            "passport.sohu.com",
            "mpfe/v4/login",
            "sso.sohu.com",
        )
    )


async def _dismiss_overlays(page: Page) -> None:
    close_candidates = [
        'button:has-text("知道了")',
        'button:has-text("我知道了")',
        'button:has-text("暂不")',
        'button:has-text("关闭")',
        'button:has-text("取消")',
        '[class*="close"]',
        '[aria-label="Close"]',
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


async def _has_dashboard_markers(page: Page) -> bool:
    markers = [
        'text=内容管理',
        'text=写文章',
        'text=发文',
        'a[href*="addarticle"]',
        'a[href*="contentManagement"]',
        'a[href*="content/list"]',
    ]
    for sel in markers:
        try:
            if await page.locator(sel).count():
                return True
        except Exception:
            continue
    return False


async def _cookie_auth_ok(page: Page) -> bool:
    url = page.url
    if _is_login_url(url):
        return False
    if await _has_dashboard_markers(page):
        return True
    if "mp.sohu.com" in url and not _is_login_url(url):
        return True
    return False


async def cookie_auth(account_file) -> bool:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(**_build_launch_kwargs(headless=LOCAL_CHROME_HEADLESS))
        try:
            context = await browser.new_context(storage_state=account_file)
            context = await _prepare_context(context)
            page = await context.new_page()
            await page.goto(SOHU_CONTENT_LIST_URL, timeout=60000)
            await page.wait_for_timeout(3000)

            if await _cookie_auth_ok(page):
                sohu_logger.success("[+] 搜狐号 cookie 有效")
                return True
            sohu_logger.error("[+] 搜狐号 cookie 失效")
            return False
        except Exception as exc:
            sohu_logger.warning(f"[+] cookie 校验异常，按失效处理: {exc}")
            return False
        finally:
            await browser.close()


async def sohu_cookie_gen(account_file):
    """CLI/本地调试用：打开登录页，手动登录后保存 cookie。"""
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(**_build_launch_kwargs(headless=False))
        context = await browser.new_context()
        context = await _prepare_context(context)
        page = await context.new_page()
        await page.goto(SOHU_LOGIN_URL, timeout=60000)
        sohu_logger.info("请在浏览器中完成搜狐号登录，登录成功后回到终端按继续…")
        await page.pause()
        Path(account_file).parent.mkdir(parents=True, exist_ok=True)
        await context.storage_state(path=account_file)
        sohu_logger.success(f"cookie saved: {account_file}")
        await context.close()
        await browser.close()


async def sohu_setup(account_file, handle=False):
    if not os.path.exists(account_file) or not await cookie_auth(account_file):
        if not handle:
            return False
        sohu_logger.error("cookie文件不存在或已失效，即将打开浏览器，请手动登录搜狐号")
        await sohu_cookie_gen(account_file)
    return True


class SoHuArticle(object):
    """搜狐号图文文章发布。"""

    def __init__(
        self,
        title,
        body,
        tags,
        publish_date: datetime | int,
        account_file,
        dry_run=False,
        cover_path=None,
        cover_paths=None,
        info_source=None,
    ):
        self.title = (title or "").strip()[:72]
        if len(self.title) < 5:
            raise ValueError("搜狐号文章标题需 5-72 个字")
        self.body = body or ""
        self.tags = tags or []
        self.publish_date = publish_date
        self.account_file = account_file
        self.headless = LOCAL_CHROME_HEADLESS if not dry_run else False
        self.dry_run = bool(dry_run)
        self.cover_paths = self._normalize_cover_paths(cover_path, cover_paths)
        self.cover_path = self.cover_paths[0] if self.cover_paths else None
        self.info_source = self._normalize_info_source(info_source)

    @staticmethod
    def _normalize_cover_paths(cover_path, cover_paths) -> list[str]:
        paths: list[str] = []
        if cover_paths:
            if isinstance(cover_paths, str):
                paths.extend(x.strip() for x in cover_paths.split(",") if x.strip())
            else:
                try:
                    paths.extend(str(x).strip() for x in cover_paths if str(x).strip())
                except TypeError:
                    if str(cover_paths).strip():
                        paths.append(str(cover_paths).strip())
        if cover_path and str(cover_path).strip():
            one = str(cover_path).strip()
            if one not in paths:
                paths.insert(0, one)
        # 去重保序
        seen = set()
        out = []
        for p in paths:
            if p not in seen:
                seen.add(p)
                out.append(p)
        return out

    @staticmethod
    def _normalize_info_source(info_source) -> str:
        """规范化信息来源（单选）。兼容字符串或单元素列表。"""
        if info_source is None or info_source == "":
            return SOHU_INFO_SOURCE_DEFAULT
        if isinstance(info_source, (list, tuple)):
            raw = next((str(x).strip() for x in info_source if str(x).strip()), "")
        else:
            raw = str(info_source).strip()
        if not raw:
            return SOHU_INFO_SOURCE_DEFAULT

        aliases = {
            "无": "无特别声明",
            "无特别": "无特别声明",
            "引用": "引用声明",
            "ai": "包含AI创作内容",
            "AI": "包含AI创作内容",
            "包含ai": "包含AI创作内容",
            "包含AI": "包含AI创作内容",
            "虚构": "包含虚构创作",
            "虚构创作": "包含虚构创作",
        }
        text = aliases.get(raw, aliases.get(raw.lower(), raw))
        if text in SOHU_INFO_SOURCE_OPTIONS:
            return text
        matched = next(
            (opt for opt in SOHU_INFO_SOURCE_OPTIONS if opt.startswith(text) or text in opt),
            None,
        )
        if matched:
            return matched
        sohu_logger.warning(f"未知信息来源「{raw}」，回退为「{SOHU_INFO_SOURCE_DEFAULT}」")
        return SOHU_INFO_SOURCE_DEFAULT

    def _normalize_tags(self) -> list[str]:
        tags = [str(t).strip().lstrip("#") for t in (self.tags or []) if str(t).strip()]
        return tags[:10]

    async def fill_title(self, page: Page) -> None:
        if len(self.title) < 5:
            raise ValueError("搜狐号文章标题需 5-72 个字")
        candidates = [
            page.locator(TITLE_INPUT_SELECTOR).first,
            page.get_by_placeholder("请输入标题").first,
            page.locator(".title-input input").first,
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
            raise RuntimeError("未找到搜狐号文章标题输入框")

        await title_field.click(force=True)
        await title_field.fill("")
        await page.wait_for_timeout(200)
        title_text = self.title
        await title_field.fill(title_text)
        sohu_logger.info(f"已填写文章标题: {title_text}")

    async def _find_editor(self, page: Page):
        selectors = [
            ".ql-editor",
            '[contenteditable="true"]',
            'div[role="textbox"]',
            ".ProseMirror",
            ".public-DraftEditor-content",
            'div[class*="editor"] [contenteditable="true"]',
            'div[class*="editor-content"]',
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
            sohu_logger.info("正文已通过剪贴板粘贴")
        except Exception as exc:
            sohu_logger.warning(f"剪贴板粘贴正文失败，尝试键盘输入: {exc}")

        if not filled:
            try:
                await editor.click(force=True)
                await page.keyboard.press("Control+A")
                await page.keyboard.press("Backspace")
                chunk_size = 200
                for i in range(0, len(text), chunk_size):
                    await page.keyboard.type(text[i : i + chunk_size], delay=5)
                filled = True
                sohu_logger.info("正文已通过键盘输入")
            except Exception as exc:
                sohu_logger.warning(f"键盘输入正文失败，尝试 DOM 写入: {exc}")

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
            sohu_logger.info("正文已通过 DOM 写入")

    async def fill_body(self, page: Page) -> None:
        tags = self._normalize_tags()
        body_text = (self.body or "").rstrip()
        if tags:
            tag_line = " ".join(f"#{t}" for t in tags)
            body_text = f"{body_text}\n\n{tag_line}" if body_text else tag_line
        if not body_text.strip():
            raise ValueError("文章正文不能为空")

        _frame, editor = await self._find_editor(page)
        if not editor:
            raise RuntimeError("未找到搜狐号正文编辑器")

        await self._paste_or_type_text(page, editor, body_text)
        sohu_logger.info(f"已填写正文，长度={len(body_text)}")

    async def handle_cover(self, page: Page) -> None:
        """搜狐封面：点击「上传图片」→ 切「本地上传」→ 选图 → 确定。

        官方限制：尺寸大于 450*300，最大 10M，jpg/jpeg/png；弹窗最多选 1 张。
        """
        covers = []
        for raw in self.cover_paths or ([] if not self.cover_path else [self.cover_path]):
            cover = Path(str(raw))
            if not cover.exists():
                sohu_logger.warning(f"封面文件不存在，跳过: {cover}")
                continue
            size = cover.stat().st_size
            if size > 10 * 1024 * 1024:
                sohu_logger.warning(f"封面超过 10MB，跳过: {cover}")
                continue
            if cover.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
                sohu_logger.warning(f"封面格式不支持（需 jpg/jpeg/png），跳过: {cover}")
                continue
            dims = self._image_size(cover)
            if dims and (dims[0] <= 450 or dims[1] <= 300):
                sohu_logger.warning(
                    f"封面尺寸需大于 450*300，当前 {dims[0]}*{dims[1]}，跳过: {cover}"
                )
                continue
            covers.append(str(cover.resolve()))

        if not covers:
            sohu_logger.info("未提供可用封面，跳过封面设置")
            return

        # 弹窗「最多可选择1张封面图」
        cover_file = covers[0]
        if len(covers) > 1:
            sohu_logger.warning(f"搜狐封面弹窗仅支持 1 张，将使用第一张，忽略其余 {len(covers) - 1} 张")

        sohu_logger.info(f"开始上传封面: {cover_file}")
        try:
            await page.locator(".cover-title").first.scroll_into_view_if_needed(timeout=5000)
        except Exception:
            try:
                await page.get_by_text("封面", exact=True).first.scroll_into_view_if_needed(timeout=3000)
            except Exception:
                pass

        try:
            trigger = page.locator(".cover-button .upload-file, .cover-button .upload-tip").first
            if not await trigger.count():
                trigger = page.get_by_text("上传图片", exact=True).first
            await trigger.click(force=True)
            await page.wait_for_timeout(600)

            # 页面上常有多个隐藏 el-dialog，定位「正文图片/本地上传」可见弹窗
            dialog_index = await page.evaluate(
                """() => {
                  const dialogs = [...document.querySelectorAll('.el-dialog')];
                  for (let i = 0; i < dialogs.length; i++) {
                    const d = dialogs[i];
                    const wrap = d.closest('.el-dialog__wrapper') || d.parentElement;
                    if (wrap && getComputedStyle(wrap).display === 'none') continue;
                    const t = d.innerText || '';
                    if (t.includes('正文图片') || t.includes('本地上传') || t.includes('最多可选择')) return i;
                  }
                  return -1;
                }"""
            )
            if dialog_index < 0:
                raise RuntimeError("未找到搜狐封面对话框")
            dialog = page.locator(".el-dialog").nth(dialog_index)

            # 默认在「正文图片」；必须切到「本地上传」
            switched = await page.evaluate(
                """(idx) => {
                  const d = document.querySelectorAll('.el-dialog')[idx];
                  if (!d) return false;
                  const tab = [...d.querySelectorAll('*')].find(el =>
                    [...el.childNodes].some(n => n.nodeType === 3 && (n.textContent || '').trim() === '本地上传')
                  );
                  if (!tab) return false;
                  tab.click();
                  return true;
                }""",
                dialog_index,
            )
            if not switched:
                sohu_logger.warning("切换「本地上传」失败，尝试继续上传")
            await page.wait_for_timeout(400)

            file_input = dialog.locator('input[type="file"]').first
            if not await file_input.count():
                file_input = page.locator('.el-dialog input[type="file"]').last
            await file_input.set_input_files(cover_file)
            sohu_logger.info("已向封面对话框写入本地图片，等待选中…")

            selected = False
            for _ in range(30):
                await page.wait_for_timeout(400)
                try:
                    text = await dialog.inner_text(timeout=2000)
                except Exception:
                    text = ""
                m = re.search(r"已选择\s*(\d+)", text or "")
                if m and int(m.group(1)) >= 1:
                    selected = True
                    sohu_logger.success(f"封面已选中：{m.group(0)}")
                    break

            if not selected:
                sohu_logger.warning("封面上传后未检测到「已选择」，尝试继续点确定")

            # 确认按钮是 <p class="positive-button">确定</p>，不是原生 button
            clicked = False
            try:
                confirm = dialog.locator("p.positive-button, .positive-button").filter(has_text="确定").first
                if await confirm.count():
                    await confirm.click(force=True, timeout=5000)
                    clicked = True
                    sohu_logger.info("已点击封面弹窗「确定」")
            except Exception as exc:
                sohu_logger.debug(f"positive-button 点击失败: {exc}")

            if not clicked:
                clicked = await page.evaluate(
                    """() => {
                      const dialogs = [...document.querySelectorAll('.el-dialog')];
                      for (const d of dialogs) {
                        const wrap = d.closest('.el-dialog__wrapper') || d.parentElement;
                        if (wrap && getComputedStyle(wrap).display === 'none') continue;
                        const t = d.innerText || '';
                        if (!(t.includes('已选择') || t.includes('最多可选择') || t.includes('正文图片'))) continue;
                        const oks = [...d.querySelectorAll('p.positive-button, .positive-button, button, .el-button')]
                          .filter(b => (b.innerText || '').trim() === '确定');
                        oks.sort((a, b) => b.getBoundingClientRect().y - a.getBoundingClientRect().y);
                        if (!oks.length) continue;
                        oks[0].click();
                        return true;
                      }
                      return false;
                    }"""
                )
            if not clicked:
                sohu_logger.warning("未能点击封面弹窗「确定」")
            await page.wait_for_timeout(1500)

            # 成功标志：.pic-cover 显示且有真实背景图
            ready = await page.evaluate(
                """() => {
                  const pic = document.querySelector('.pic-cover');
                  if (!pic) return false;
                  const st = getComputedStyle(pic);
                  const bg = st.backgroundImage || '';
                  return st.display !== 'none' && (bg.includes('http') || bg.includes('blob:'));
                }"""
            )
            if ready:
                sohu_logger.success("封面已应用到发文页")
            else:
                sohu_logger.warning("已点击确定，但未检测到封面预览，请 dry_run 人工确认")
            await _dismiss_overlays(page)
        except Exception as exc:
            sohu_logger.warning(f"封面设置失败（可忽略）: {exc}")

    @staticmethod
    def _image_size(path: Path) -> tuple[int, int] | None:
        """读取图片宽高；失败返回 None（不阻断上传，交由页面校验）。"""
        try:
            data = path.read_bytes()
        except Exception:
            return None
        try:
            if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
                w = int.from_bytes(data[16:20], "big")
                h = int.from_bytes(data[20:24], "big")
                return w, h
            if data[:2] == b"\xff\xd8":
                i = 2
                n = len(data)
                while i < n - 8:
                    if data[i] != 0xFF:
                        i += 1
                        continue
                    marker = data[i + 1]
                    if marker in (0xC0, 0xC1, 0xC2, 0xC3):
                        h = int.from_bytes(data[i + 5 : i + 7], "big")
                        w = int.from_bytes(data[i + 7 : i + 9], "big")
                        return w, h
                    if marker in (0xD8, 0xD9) or (0xD0 <= marker <= 0xD7):
                        i += 2
                        continue
                    if marker == 0x01:
                        i += 2
                        continue
                    if i + 4 > n:
                        break
                    length = int.from_bytes(data[i + 2 : i + 4], "big")
                    i += 2 + length
        except Exception:
            return None
        return None

    async def apply_info_source(self, page: Page) -> None:
        """选择发文页「信息来源」单选项。"""
        label = self.info_source or SOHU_INFO_SOURCE_DEFAULT
        sohu_logger.info(f"设置信息来源: {label}")
        try:
            try:
                section = page.get_by_text("信息来源", exact=False).first
                if await section.count():
                    await section.scroll_into_view_if_needed(timeout=3000)
            except Exception:
                await page.evaluate(
                    "window.scrollTo(0, Math.max(document.body.scrollHeight * 0.5, 700))"
                )
            await page.wait_for_timeout(300)

            # 优先在「信息来源」附近查找选项，避免误点其它区域
            scopes = []
            for sel in (
                'div:has-text("信息来源"):has-text("无特别声明")',
                'div:has-text("信息来源"):has-text("引用声明")',
                'section:has-text("信息来源")',
                'div:has-text("信息来源")',
            ):
                try:
                    loc = page.locator(sel)
                    count = await loc.count()
                    best = None
                    best_h = 10**9
                    for i in range(min(count, 8)):
                        item = loc.nth(i)
                        box = await item.bounding_box()
                        if not box:
                            continue
                        h = box.get("height") or 0
                        w = box.get("width") or 0
                        if 20 < h < 200 and w > 200 and h < best_h:
                            best = item
                            best_h = h
                    if best is not None:
                        scopes.append(best)
                        break
                except Exception:
                    continue
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
                            scope.locator(f'label:has-text("{label}") input[type="radio"]'),
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
                        box = await item.bounding_box()
                        if box and (box.get("height") or 0) > 60:
                            continue
                        text = ""
                        try:
                            text = ((await item.inner_text()) or "").strip().replace("\n", " ")
                        except Exception:
                            pass
                        if text and label not in text:
                            continue
                        if text and len(text) > max(len(label) + 12, 40):
                            continue

                        # 已选中则跳过
                        try:
                            radio = item.locator('input[type="radio"]').first
                            if await radio.count() and await radio.is_checked():
                                sohu_logger.info(f"信息来源已是「{label}」")
                                return
                            # 自身可能是 radio
                            tag = (await item.evaluate("el => el.tagName")).lower()
                            if tag == "input":
                                if await item.is_checked():
                                    sohu_logger.info(f"信息来源已是「{label}」")
                                    return
                        except Exception:
                            pass

                        try:
                            radio = item.locator('input[type="radio"]').first
                            if await radio.count():
                                await radio.check(force=True, timeout=2000)
                            else:
                                await item.click(timeout=2500, force=True)
                        except Exception:
                            await item.click(timeout=2500, force=True)
                        await page.wait_for_timeout(300)
                        sohu_logger.success(f"已选择信息来源: {label}")
                        return
                    except Exception:
                        continue

            sohu_logger.warning(f"未能选择信息来源「{label}」，请 dry_run 人工确认")
        except Exception as exc:
            sohu_logger.warning(f"设置信息来源失败（可忽略）: {exc}")

    async def fill_tags(self, page: Page) -> None:
        """若页面有独立标签输入框则填写；否则标签已写入正文。"""
        tags = self._normalize_tags()
        if not tags:
            return
        candidates = [
            page.locator('input[placeholder*="标签"]').first,
            page.locator('input[placeholder*="话题"]').first,
            page.locator('input[placeholder*="添加标签"]').first,
            page.get_by_placeholder("请输入标签").first,
        ]
        tag_field = None
        for loc in candidates:
            try:
                if await loc.count() and await loc.is_visible():
                    tag_field = loc
                    break
            except Exception:
                continue
        if not tag_field:
            sohu_logger.info("未找到独立标签输入框，标签已写入正文（如适用）")
            return

        for tag in tags:
            try:
                await tag_field.click(force=True)
                await tag_field.fill(tag)
                await page.keyboard.press("Enter")
                await page.wait_for_timeout(300)
            except Exception as exc:
                sohu_logger.warning(f"填写标签失败 {tag}: {exc}")
                break
        sohu_logger.info(f"已尝试填写标签: {tags}")

    async def set_schedule_time(self, page: Page, publish_date: datetime) -> None:
        sohu_logger.info(f"尝试设置定时发布: {publish_date}")
        try:
            for label in ("定时发布", "定时", "预约发布"):
                try:
                    loc = page.get_by_text(label, exact=False).first
                    if await loc.count() and await loc.is_visible():
                        await loc.click(timeout=3000, force=True)
                        await page.wait_for_timeout(500)
                        break
                except Exception:
                    continue
            date_str = publish_date.strftime("%Y-%m-%d %H:%M")
            time_inputs = [
                page.locator('input[placeholder*="时间"]').first,
                page.locator('input[placeholder*="日期"]').first,
                page.locator('input[type="datetime-local"]').first,
            ]
            for loc in time_inputs:
                try:
                    if await loc.count() and await loc.is_visible():
                        await loc.fill(date_str)
                        sohu_logger.success(f"定时发布时间已填写: {date_str}")
                        return
                except Exception:
                    continue
            sohu_logger.warning("未找到定时发布时间输入框，将按立即发布处理")
        except Exception as exc:
            sohu_logger.warning(f"设置定时发布失败，将按立即发布处理: {exc}")

    async def publish(self, page: Page) -> None:
        if self.publish_date != 0 and isinstance(self.publish_date, datetime):
            await self.set_schedule_time(page, self.publish_date)

        await _dismiss_overlays(page)
        publish_candidates = [
            page.locator('button:has-text("发布")').last,
            page.get_by_role("button", name="发布").last,
            page.locator('button:has-text("立即发布")').last,
            page.locator('span:has-text("发布")').last,
        ]
        clicked = False
        for btn in publish_candidates:
            try:
                if await btn.count() and await btn.is_visible():
                    await btn.scroll_into_view_if_needed()
                    await btn.click(force=True, timeout=15000)
                    clicked = True
                    break
            except Exception:
                continue

        if not clicked:
            clicked = await page.evaluate(
                """() => {
                    const nodes = Array.from(document.querySelectorAll('button, a, span, div'));
                    const match = nodes.find(el => {
                        const t = (el.innerText || el.textContent || '').trim();
                        return t === '发布' || t === '立即发布';
                    });
                    if (!match) return false;
                    match.click();
                    return true;
                }"""
            )
        if not clicked:
            raise RuntimeError("未找到可点击的「发布」按钮")
        await page.wait_for_timeout(3000)
        sohu_logger.success("已点击文章发布")

    async def _title_input_ready(self, page: Page) -> bool:
        try:
            return bool(await page.locator(TITLE_INPUT_SELECTOR).count())
        except Exception:
            return False

    async def _editor_ready(self, page: Page) -> bool:
        _frame, editor = await self._find_editor(page)
        return editor is not None

    async def _publish_form_ready(self, page: Page) -> bool:
        return await self._editor_ready(page) or await self._title_input_ready(page)

    async def _visible_captcha(self, page: Page) -> bool:
        """仅当验证码真正挡住操作时才判定。

        搜狐页常驻 tcaptcha iframe（甚至带宽高），不能仅凭 DOM 存在就报滑块。
        要求：iframe 在视口内且页面出现验证相关文案。
        """
        try:
            has_visible_frame = bool(
                await page.evaluate(
                    """() => {
                      const nodes = [...document.querySelectorAll(
                        '#tcaptcha_iframe_dy, iframe[src*="captcha"], iframe[src*="turing.captcha"], iframe[src*="gtimg.com"]'
                      )];
                      const vh = window.innerHeight || 800;
                      const vw = window.innerWidth || 1200;
                      return nodes.some(f => {
                        const r = f.getBoundingClientRect();
                        const s = getComputedStyle(f);
                        if (s.display === 'none' || s.visibility === 'hidden') return false;
                        if (Number(s.opacity || '1') === 0) return false;
                        if (r.width < 120 || r.height < 80) return false;
                        // 必须落在视口内（排除藏在角落/屏外的常驻 iframe）
                        const inView = r.bottom > 40 && r.top < vh - 40 && r.right > 40 && r.left < vw - 40;
                        return inView;
                      });
                    }"""
                )
            )
            if not has_visible_frame:
                return False
            body = ((await page.inner_text("body")) or "")[:2500]
            keywords = ("请向右拖动", "安全验证", "滑动验证", "完成验证", "拖动滑块")
            return any(k in body for k in keywords)
        except Exception:
            return False

    async def _detect_blocking_state(self, page: Page) -> str:
        """返回阻塞原因文案；无阻塞返回空字符串。"""
        try:
            body = ((await page.inner_text("body")) or "")[:2000]
        except Exception:
            body = ""
        if "主体信息已过期" in body:
            return "账号提示「主体信息已过期」，请先在搜狐号后台重新提交主体信息后再发文"
        # 「实名认证」黄条在很多账号上只是提示，手工发文同样可发，不当作硬阻塞
        if await self._visible_captcha(page):
            return "检测到滑块/安全验证，请在浏览器中完成验证"
        if "加载中" in body and not await self._publish_form_ready(page):
            return "发文页仍在加载中"
        return ""

    async def _wait_publish_form(self, page: Page, timeout_sec: int = 180) -> bool:
        """等待发文表单出现；若遇验证码则提示并继续等待人工处理。"""
        elapsed = 0
        interval = 2
        last_tip = ""
        hard_block_at = None
        while elapsed < timeout_sec:
            if _is_login_url(page.url):
                raise RuntimeError("搜狐号 cookie 已失效，请重新登录")
            if await self._publish_form_ready(page):
                sohu_logger.success(f"发文表单已就绪（等待 {elapsed}s）")
                return True

            tip = await self._detect_blocking_state(page)
            hard = tip and ("主体信息已过期" in tip)
            if hard:
                if hard_block_at is None:
                    hard_block_at = elapsed
                    sohu_logger.error(tip)
                elif elapsed - hard_block_at >= 20:
                    raise RuntimeError(tip)
            elif tip and tip != last_tip:
                sohu_logger.warning(f"{tip}；页面将保持打开，最多再等 {timeout_sec - elapsed}s")
                last_tip = tip
            elif not tip and elapsed >= 60 and "addarticle" in (page.url or ""):
                # 无明确验证码、也无表单：缩短空等
                sohu_logger.warning("发文页持续加载且无表单，可能账号权限不足或页面改版")

            await asyncio.sleep(interval)
            elapsed += interval
            if elapsed % 30 == 0:
                sohu_logger.info(f"仍在等待搜狐发文页…{elapsed}s / {timeout_sec}s url={page.url}")
        return False

    async def _ensure_article_editor_url(self, page: Page) -> None:
        """确保落在图文发文页 addarticle，而不是动态页 addmoment。"""
        url = page.url or ""
        if "addmoment" in url or ("addarticle" not in url):
            target = "https://mp.sohu.com/mpfe/v4/contentManagement/news/addarticle"
            sohu_logger.info(f"当前不在图文发文页（{url}），改打开 {target}")
            await page.goto(target, timeout=60000, wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)

    async def _click_publish_menu(self, page: Page) -> bool:
        """点击左侧「发布内容」菜单（用户提供的稳定节点）。"""
        candidates = [
            page.locator('xpath=//*[@id="menu-ic_publish"]/div/div').first,
            page.locator("#menu-ic_publish >> div >> div").first,
            page.locator("#menu-ic_publish").first,
            page.locator('[id="menu-ic_publish"]').first,
        ]
        for loc in candidates:
            try:
                if not await loc.count():
                    continue
                await loc.scroll_into_view_if_needed(timeout=3000)
                await loc.click(force=True, timeout=8000)
                sohu_logger.info("已点击 #menu-ic_publish 发布内容入口")
                await page.wait_for_timeout(1500)
                # 该菜单默认会进 addmoment（动态）；图文需再切到 addarticle
                await self._ensure_article_editor_url(page)
                return True
            except Exception as exc:
                sohu_logger.debug(f"点击 menu-ic_publish 失败: {exc}")
                continue

        for text in ("发布内容", "写文章", "发文", "新建图文"):
            try:
                loc = page.get_by_text(text, exact=False).first
                if await loc.count() and await loc.is_visible():
                    await loc.click(timeout=5000, force=True)
                    sohu_logger.info(f"已点击文本入口「{text}」")
                    await page.wait_for_timeout(1500)
                    await self._ensure_article_editor_url(page)
                    return True
            except Exception:
                continue
        return False

    async def _open_via_publish_menu(self, page: Page) -> bool:
        """先进入后台会话，再打开图文发文页 addarticle。"""
        for start in (SOHU_FIRST_PAGE_URL, SOHU_HOME_URL, SOHU_CONTENT_LIST_URL):
            try:
                sohu_logger.info(f"打开搜狐后台入口: {start}")
                await page.goto(start, timeout=60000, wait_until="domcontentloaded")
                await page.wait_for_timeout(3000)
                await _dismiss_overlays(page)
                if _is_login_url(page.url):
                    raise RuntimeError("搜狐号 cookie 已失效，请重新登录")

                # 建立会话后直接进图文页（比点菜单更稳；菜单默认进 addmoment）
                await self._ensure_article_editor_url(page)
                if await self._wait_publish_form(page, timeout_sec=90):
                    return True

                # 表单未出时再点一次发布菜单并强制切回 addarticle
                try:
                    await page.locator("#menu-ic_publish").first.wait_for(state="attached", timeout=8000)
                except Exception:
                    pass
                if await self._click_publish_menu(page):
                    if await self._wait_publish_form(page, timeout_sec=120):
                        return True
            except RuntimeError:
                raise
            except Exception as exc:
                sohu_logger.warning(f"从 {start} 进入发文失败: {exc}")
        return False

    async def _open_article_editor(self, page: Page) -> None:
        opened = False

        # 1) 优先菜单进入（探测证实：点击「发布内容」会到 addarticle）
        try:
            opened = await self._open_via_publish_menu(page)
        except RuntimeError:
            raise
        except Exception as exc:
            sohu_logger.warning(f"菜单进入发文页异常: {exc}")

        # 2) 直链兜底
        if not opened:
            for url in SOHU_ARTICLE_URLS:
                try:
                    sohu_logger.info(f"正在打开搜狐号图文发布页... {url}")
                    await page.goto(url, timeout=60000, wait_until="domcontentloaded")
                    await page.wait_for_timeout(2000)
                    await _dismiss_overlays(page)
                    if _is_login_url(page.url):
                        raise RuntimeError("搜狐号 cookie 已失效，请重新登录")
                    if await self._wait_publish_form(page, timeout_sec=90):
                        opened = True
                        break
                except RuntimeError:
                    raise
                except Exception as exc:
                    sohu_logger.warning(f"打开 {url} 失败: {exc}")

        if not opened:
            tip = await self._detect_blocking_state(page)
            try:
                shot = Path(self.account_file).with_name("sohu_open_editor_fail.png")
                await page.screenshot(full_page=True, path=str(shot))
                sohu_logger.warning(f"打开发文页失败截图: {shot}")
            except Exception:
                pass
            extra = f"；当前状态：{tip}" if tip else ""
            raise RuntimeError(
                "无法打开搜狐号图文发布页，请检查账号权限、是否完成滑块验证，或后台是否提示主体信息过期"
                + extra
            )

    async def upload(self, playwright: Playwright) -> None:
        if not (self.body or "").strip() and not self.tags:
            raise ValueError("文章正文不能为空")

        # 搜狐发文页常出滑块验证，强制有头方便人工处理
        launch_kwargs = _build_launch_kwargs(False)
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
        context = await _prepare_context(context)
        page = await context.new_page()

        await self._open_article_editor(page)

        await self.fill_title(page)
        await page.wait_for_timeout(500)
        await self.fill_body(page)
        await self.fill_tags(page)
        await self.handle_cover(page)
        await self.apply_info_source(page)
        await _dismiss_overlays(page)

        if self.dry_run:
            sohu_logger.warning("🛑 【仅预览不发布】已跳过点击发布按钮")
            sohu_logger.info("👀 请在浏览器窗口核对：标题、正文、标签、封面、信息来源")
            try:
                await page.screenshot(
                    full_page=True,
                    path=str(Path(self.account_file).with_name("sohu_article_dry_run_preview.png")),
                )
            except Exception:
                pass
            for _ in range(120):
                await asyncio.sleep(1)
            sohu_logger.info("🛑 预览结束，关闭浏览器（未点击发布）")
        else:
            await self.publish(page)
            await page.wait_for_timeout(3000)
            sohu_logger.success("文章发布流程完成")

        await context.storage_state(path=self.account_file)
        sohu_logger.info("cookie 更新完毕")
        await asyncio.sleep(1)
        await context.close()
        await browser.close()

    async def main(self):
        async with async_playwright() as playwright:
            await self.upload(playwright)
