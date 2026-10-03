"""微信公众号原生文章；草稿保存不属于发表。

入口和现代编辑器字段参考 baoyu-post-to-wechat/wechat-article.ts 与
MediaSync/platforms/weixin.ts；发表入口参考公开 wechat-auto-publisher。
公开实现只提供控件线索，不能替代当前账号验收。无法唯一确认时停止。
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlencode, urlparse

from utils.articles.browser import PreparationError, is_uploaded_image, normalize_text
from utils.articles.native import NativeArticleAdapter, _unique, _value


# 仅读取编辑器外的可见平台反馈，正文里的“扫码”“发表成功”都不是回执。
_EXTERNAL_TEXT = """elements => elements.filter(el => {
    if (el.closest('[contenteditable],.ProseMirror,.rich_media_content,.edui-editor')) return false;
    const rect = el.getBoundingClientRect(), style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
}).map(el => (el.innerText || '').trim())"""
_DIALOGS = '[role="dialog"],.weui-desktop-dialog,.dialog_wrp'
_FEEDBACK = '[role="alert"],.weui-desktop-toast,.weui-desktop-msg,.page_msg,.global_tips'
_PUBLISH_TEXT = re.compile(r"^(?:确认|确定|立即)?(?:发表|发布)$")


class WechatArticleAdapter(NativeArticleAdapter):
    """在独立公众号账号中准备文章，正式发表前先记录不可重试边界。"""

    platform, label = "wechat", "微信公众号"
    editor_url = "https://mp.weixin.qq.com/"
    title_selector = 'input#title,textarea#title'
    editor_selector = '.rich_media_content .ProseMirror[contenteditable="true"]'
    summary_selector = 'textarea#js_description,input#js_description'
    # 旧版命名区域或明确标注的原生封面区；不从正文或整页挑第一张图片。
    cover_region_selector = '#js_cover_area,[role="group"][aria-label="封面"]'

    async def open_editor(self, page):
        """从已登录首页获取本次 token；不在代码或任务结果中保存该凭据。"""
        await page.goto(self.editor_url, timeout=60000, wait_until="domcontentloaded")
        try:
            await page.wait_for_url(re.compile(r"^https://mp\.weixin\.qq\.com/cgi-bin/"), timeout=15000)
        except Exception as exc:
            raise PreparationError("微信公众号登录已失效，请使用公众号账号重新扫码登录") from exc
        current = urlparse(page.url)
        tokens = parse_qs(current.query).get("token", [])
        if (current.scheme != "https" or current.netloc != "mp.weixin.qq.com"
                or not current.path.startswith("/cgi-bin/") or len(tokens) != 1
                or not re.fullmatch(r"[1-9][0-9]*", tokens[0])):
            raise PreparationError("未确认微信公众号登录会话，请重新扫码登录")
        if await self._has_challenge(page):
            raise PreparationError("微信公众号要求扫码或安全验证，请先在平台完成验证")
        # 新建入口不带 appmsgid，不能覆盖已有草稿。标题及正文还须独立读回。
        query = urlencode({"t": "media/appmsg_edit", "action": "edit", "type": "77",
                           "isNew": "1", "token": tokens[0], "lang": "zh_CN"})
        try:
            await page.goto("https://mp.weixin.qq.com/cgi-bin/appmsg?" + query,
                            timeout=60000, wait_until="domcontentloaded")
        except Exception as exc:
            # Playwright 原始错误可能包含带 token 的完整 URL，不能保存到任务消息。
            raise PreparationError("微信公众号文章编辑器加载失败，请检查网络或重新登录") from exc
        try:
            await page.locator(self.title_selector).first.wait_for(state="visible", timeout=20000)
        except Exception as exc:
            raise PreparationError("未找到微信公众号文章编辑器，请检查扫码登录状态及文章权限") from exc
        location = urlparse(page.url)
        if (location.scheme != "https" or location.netloc != "mp.weixin.qq.com"
                or location.path != "/cgi-bin/appmsg"):
            raise PreparationError("微信公众号未进入原生文章编辑器，请检查登录及文章权限")
        if parse_qs(location.query).get("appmsgid"):
            raise PreparationError("微信公众号打开了已有草稿，已停止以防覆盖原文")
        await self._title_field(page)
        modern = page.locator(self.editor_selector)
        if await modern.count():
            return await _unique(modern, "微信公众号文章正文编辑器")
        iframe = await _unique(page.locator('.edui-editor-iframeholder iframe'),
                               "微信公众号文章 UEditor 框架")
        handle = await iframe.element_handle()
        frame = await handle.content_frame() if handle else None
        if frame is None:
            raise PreparationError("微信公众号正文编辑器未就绪，请人工核对")
        return await _unique(frame.locator('body[contenteditable="true"]'), "微信公众号文章正文编辑器")

    async def _has_challenge(self, page):
        """仅识别可见验证弹层和登录二维码，不能被正文中的文字触发。"""
        texts = await page.locator(_DIALOGS + "," + _FEEDBACK + ",.login__type__container__scan,.login_qrcode_area").evaluate_all(_EXTERNAL_TEXT)
        return any(re.search(r"(?:扫码|扫描二维码|微信扫一扫|安全验证|管理员确认|管理员验证|手机验证|验证码)", text)
                   for text in texts)

    async def _author_field(self, page):
        return await _unique(page.locator('input#author,textarea#author'), "微信公众号作者", enabled=True)

    async def apply_options(self, page, editor):
        """仅支持已确认的摘要和作者；其他显式选项不能无声丢弃。"""
        unknown = [key for key, value in self.options.items()
                   if key not in {"summary", "author"} and value not in (None, "", False)]
        if unknown:
            raise PreparationError("微信公众号不支持的文章选项：" + "、".join(unknown))
        if self.tags:
            raise PreparationError("尚未确认微信公众号原生话题控件，请移除话题或人工设置")
        if not self.cover:
            raise PreparationError("微信公众号文章需要封面，请选择封面素材")
        for name, expected, maximum in (("summary", self.options.get("summary"), 120),
                                         ("author", self.options.get("author"), 8)):
            if not expected:
                continue
            field = await (self._summary_field(page) if name == "summary" else self._author_field(page))
            declared = await field.get_attribute("maxlength")
            limit = min(maximum, int(declared)) if declared and declared.isdigit() and int(declared) > 0 else maximum
            if len(expected) > limit:
                raise PreparationError(f"微信公众号{'摘要' if name == 'summary' else '作者'}最多 {limit} 字")
            await field.fill(expected)
        self._cover_before = {item["src"] for item in await self._cover_images(page)}
        await self._upload_cover(page)

    async def verify_options(self, page, editor):
        for name, expected in (("summary", self.options.get("summary")), ("author", self.options.get("author"))):
            if expected:
                field = await (self._summary_field(page) if name == "summary" else self._author_field(page))
                if await _value(field) != expected:
                    raise PreparationError(f"微信公众号{'摘要' if name == 'summary' else '作者'}读回不一致，已阻止发表")
        images = await self._cover_images(page)
        if not self.cover or not any(is_uploaded_image(item, self.platform) and item["src"] not in self._cover_before
                                     for item in images):
            raise PreparationError("未确认微信公众号新封面上传完成，已阻止发表")

    async def _cover_region(self, page):
        return await _unique(page.locator(self.cover_region_selector), "微信公众号封面区域")

    async def _cover_images(self, page):
        region = await self._cover_region(page)
        return await region.locator('img').evaluate_all("""images => images.map(img => ({
            src: img.src || '', ready: img.complete && img.naturalWidth > 0}))""")

    async def _upload_cover(self, page):
        """只操作封面区的图片字段；裁剪确认必须来自明确的封面弹层。"""
        region = await self._cover_region(page)
        field = await _unique(region.locator('input[type="file"][accept*="image"]'),
                              "微信公众号封面上传字段", visible=False)
        await field.set_input_files(str(self.cover))
        # 某些版本直接设置封面，另一些版本需要裁剪；只等待，绝不重复上传。
        for _ in range(30):
            images = await self._cover_images(page)
            if any(is_uploaded_image(item, self.platform) and item["src"] not in self._cover_before for item in images):
                return
            dialogs = page.locator(_DIALOGS).filter(has_text=re.compile(r"封面|裁剪"))
            visible = [dialogs.nth(i) for i in range(await dialogs.count()) if await dialogs.nth(i).is_visible()]
            if visible:
                if len(visible) != 1:
                    raise PreparationError("微信公众号封面裁剪窗口不唯一，请人工处理")
                confirm = await _unique(visible[0].get_by_role("button", name=re.compile(r"^(完成|确定)$")),
                                        "微信公众号封面裁剪确认", enabled=True)
                await confirm.click(timeout=10000)
                await visible[0].wait_for(state="hidden", timeout=10000)
                await self._wait_cover_changed(page)
                return
            await page.wait_for_timeout(500)
        raise PreparationError("未确认微信公众号新封面上传完成，已阻止发表")

    async def submit(self, page, on_submit):
        """发表入口及确认各单击一次；存草稿、预览和群发不会被当作发表。"""
        if self.snapshot.get("mode") == "preview":
            raise PreparationError("微信公众号预览模式禁止发表")
        if self._submit_started:
            raise PreparationError("本任务已经尝试提交，请先核对平台记录，勿重复提交")
        if await self._has_challenge(page):
            raise PreparationError("微信公众号要求扫码或安全验证，请先在平台完成验证")
        # 只接受有明确发表名称的操作，不使用 #js_submit（它是保存草稿）。
        button = await _unique(page.get_by_role("button", name=re.compile(r"^(发表|发布)$")),
                               "微信公众号发表按钮", enabled=True)
        await button.scroll_into_view_if_needed()
        await self._mark_submit(on_submit)
        await button.click(timeout=10000)
        # 首次点击可能直接提交，也可能出现确认/扫码；只读取，避免再次找全页发表按钮。
        for _ in range(20):
            if await self._has_challenge(page):
                return
            dialogs = page.locator(_DIALOGS).filter(has_text=re.compile(r"发表|发布"))
            visible = [dialogs.nth(i) for i in range(await dialogs.count()) if await dialogs.nth(i).is_visible()]
            if visible:
                if len(visible) != 1:
                    raise PreparationError("微信公众号发表确认窗口不唯一，请核对平台记录")
                confirm = await _unique(visible[0].get_by_role("button", name=_PUBLISH_TEXT),
                                        "微信公众号最终发表确认", enabled=True)
                await confirm.click(timeout=10000)
                return
            result = await self.read_result(page)
            if result["status"] != "unknown":
                return
            await page.wait_for_timeout(500)

    async def read_result(self, page):
        """存草稿成功、appmsgid 与预览页均不能证明文章已发表。"""
        if await self._has_challenge(page):
            return {"status": "needs_action", "message": "微信公众号要求管理员扫码或安全验证，请核对平台记录后处理"}
        if not self._submit_started:
            return {"status": "unknown", "message": "尚未正式发表；保存草稿不属于发表成功"}
        parsed = urlparse(page.url)
        public = re.fullmatch(r"/s/([A-Za-z0-9_-]{10,})", parsed.path)
        query = parse_qs(parsed.query)
        if (parsed.scheme == "https" and parsed.netloc == "mp.weixin.qq.com" and public
                and not any(key in query for key in ("tempkey", "token", "is_temp_url", "preview"))):
            titles = await page.locator('#activity-name').all_text_contents()
            if len(titles) == 1 and normalize_text(titles[0]) == normalize_text(self.title):
                return {"status": "published", "message": "已打开并核对微信公众号公开文章",
                        "platform_url": page.url, "platform_id": public.group(1), "platform_status": "已发表"}
        feedback = await page.locator(_FEEDBACK).evaluate_all(_EXTERNAL_TEXT)
        for text in feedback:
            text = re.sub(r"^[✅✔✓√\ufe0f\s]+", "", text).strip()
            if re.match(r"^(?:文章)?(?:发表失败|发布失败|提交失败|审核不通过)(?=[。！!，,；;：:\n]|$)", text):
                return {"status": "failed", "message": "微信公众号反馈：" + text}
            if re.match(r"^(?:文章)?(?:发表成功|发布成功|提交成功|已发表|等待审核|审核中)(?=[。！!，,；;：:\n]|$)", text):
                return {"status": "submitted", "message": "微信公众号已确认发表提交：" + text,
                        "platform_status": text}
        return {"status": "unknown", "message": "已尝试发表，尚未获得微信公众号发表回执；草稿保存不表示发表成功，请勿重复提交"}
