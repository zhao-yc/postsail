"""懂车号原生文章；公开控件线索尚未取得真实账号验收。

入口与控件依据：
https://github.com/leaperone/MultiPost-Extension/blob/6269ab4ada1cf661a3624b2b9f496bb032a391d5/src/sync/article/dongchedi.ts
同提交 src/sync/article.ts 注册 /profile_v2/publish/article。上游自己标注
experimental；这里只复用入口与字段线索，不采用 innerHTML 注入或点击即成功。
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from utils.articles.browser import (
    PreparationError, _EXTERNAL_RECEIPT_TEXTS, has_visible_challenge, is_uploaded_image, read_result_evidence,
)
from utils.articles.native import NativeArticleAdapter, _unique


_DIALOGS = '[role="dialog"],.ant-modal,.m-dialog'


class DongchediArticleAdapter(NativeArticleAdapter):
    """标题、UEditor 正文和独立封面均读回后，才允许单次提交。"""

    platform, label = "dongchedi", "懂车号"
    editor_url = "https://mp.dcdapp.com/profile_v2/publish/article"
    # 上游只确认 textarea。必须唯一，出现摘要或额外 textarea 时停止而非选第一个。
    title_selector = 'textarea'
    editor_selector = 'div[contenteditable="true"]'

    def _validate_requested_options(self):
        unsupported = [name for name, value in self.options.items() if value not in (None, "", False)]
        if unsupported:
            raise PreparationError("懂车号尚未确认这些原生选项，请移除或人工设置：" + "、".join(unsupported))
        if self.tags:
            raise PreparationError("尚未确认懂车号原生话题控件，请清空话题或在平台人工设置")

    async def _check_editor_location(self, page):
        location = urlparse(page.url)
        if (location.scheme != "https" or location.netloc != "mp.dcdapp.com"
                or location.path.rstrip("/") != "/profile_v2/publish/article"):
            raise PreparationError("懂车号未进入文章编辑器，请重新登录并检查文章权限")
        query = parse_qs(location.query)
        if any(query.get(name) for name in ("id", "item_id", "article_id", "group_id", "draft_id")):
            raise PreparationError("懂车号打开了已有文章或草稿，已停止以防覆盖原文")
        if await self._has_challenge(page):
            raise PreparationError("懂车号要求安全验证，请先在平台完成验证")

    async def _has_challenge(self, page):
        feedback = await page.locator('[role="alert"],.ant-message,.m-message').evaluate_all(_EXTERNAL_RECEIPT_TEXTS)
        return await has_visible_challenge(page, feedback)

    async def open_editor(self, page):
        self._validate_requested_options()
        await page.goto(self.editor_url, timeout=60000, wait_until="domcontentloaded")
        await self._check_editor_location(page)
        try:
            await page.locator(self.title_selector).first.wait_for(state="visible", timeout=20000)
            await page.locator(self.editor_selector + ',iframe[id^="ueditor_"]').first.wait_for(
                state="visible", timeout=20000)
        except Exception as exc:
            raise PreparationError("未找到懂车号文章编辑器，请检查登录、文章权限或页面变化") from exc
        await self._check_editor_location(page)
        await self._title_field(page)
        direct = page.locator(self.editor_selector)
        if await direct.count():
            return await _unique(direct, "懂车号原生文章正文编辑器")
        iframe = await _unique(page.locator('iframe[id^="ueditor_"]'), "懂车号 UEditor 框架")
        handle = await iframe.element_handle()
        frame = await handle.content_frame() if handle else None
        if frame is None:
            raise PreparationError("懂车号 UEditor 正文尚未就绪")
        await frame.locator('body[contenteditable="true"]').wait_for(state="visible", timeout=10000)
        return await _unique(frame.locator('body[contenteditable="true"]'), "懂车号文章正文编辑器")

    async def _cover_region(self, page):
        trigger = await _unique(page.locator('div.fake-upload-trigger'), "懂车号封面上传入口")
        region = trigger.locator('xpath=..')
        # 父区域必须与正文和标题分离，否则正文图片会被误当作封面。
        if await region.locator('textarea,[contenteditable="true"],iframe').count():
            raise PreparationError("懂车号封面区域与正文无法区分，请在平台核对封面")
        return region

    async def _cover_images(self, page):
        return await (await self._cover_region(page)).locator('img').evaluate_all("""images => images.map(img => ({
            src: img.src || '', ready: img.complete && img.naturalWidth > 0}))""")

    async def apply_options(self, page, editor):
        self._validate_requested_options()
        if not self.cover:
            raise PreparationError("懂车号文章需要封面，请选择封面素材")
        self._cover_before = {item["src"] for item in await self._cover_images(page)}
        await self._upload_cover(page)

    async def verify_options(self, page, editor):
        self._validate_requested_options()
        if not self.cover or not any(is_uploaded_image(item, self.platform)
                                     and item["src"] not in self._cover_before
                                     for item in await self._cover_images(page)):
            raise PreparationError("未确认懂车号新封面已上传，已阻止发布")

    async def _upload_cover(self, page):
        """封面上传及裁剪各执行一次；只接受明确封面弹层内的确认按钮。"""
        trigger = await _unique(page.locator('div.fake-upload-trigger'), "懂车号封面上传入口")
        await trigger.click(timeout=10000)
        local = page.locator('li').filter(has_text=re.compile(r"^\s*本地上传\s*$"))
        await local.first.wait_for(state="visible", timeout=10000)
        await (await _unique(local, "懂车号封面本地上传菜单")).click(timeout=10000)
        field = await _unique(page.locator('div.xigua-upload-poster-trigger > input[type="file"]'),
                              "懂车号封面文件字段", visible=False)
        await field.set_input_files(str(self.cover))
        clip_done = False
        confirmed = []
        for _ in range(30):
            if any(is_uploaded_image(item, self.platform) and item["src"] not in self._cover_before
                   for item in await self._cover_images(page)):
                return
            dialogs = page.locator(_DIALOGS).filter(has_text=re.compile(r"封面|裁剪"))
            visible = [dialogs.nth(i) for i in range(await dialogs.count()) if await dialogs.nth(i).is_visible()]
            if len(visible) > 1:
                raise PreparationError("懂车号封面弹层不唯一，请人工核对")
            if visible:
                dialog = visible[0]
                clip = dialog.locator('div.clip-btn-content')
                if await clip.count() and not clip_done:
                    await (await _unique(clip, "懂车号封面裁剪按钮")).click(timeout=10000)
                    clip_done = True
                buttons = dialog.get_by_role("button", name=re.compile(r"^(确定|完成)$"))
                if await buttons.count():
                    button = await _unique(buttons, "懂车号封面确认按钮", enabled=True)
                    # 两层确认可依次出现；同一个按钮在等待中绝不能反复点击。
                    already_clicked = False
                    for handle in confirmed:
                        if await button.evaluate('(el, previous) => el === previous', handle):
                            already_clicked = True
                            break
                    if not already_clicked:
                        if len(confirmed) >= 2:
                            raise PreparationError("懂车号封面确认流程发生变化，请人工处理")
                        confirmed.append(await button.element_handle())
                        await button.click(timeout=10000)
            await page.wait_for_timeout(500)
        raise PreparationError("未确认懂车号封面已上传；本地预览和触发文件选择不表示成功")

    async def submit(self, page, on_submit):
        """预览并发布之前保存边界；最终确认须位于明确发布弹层。"""
        if self.snapshot.get("mode") == "preview":
            raise PreparationError("懂车号预览模式禁止发布")
        if self._submit_started:
            raise PreparationError("本任务已经尝试提交，请先核对平台记录，勿重复提交")
        self._validate_requested_options()
        await self._check_editor_location(page)
        button = await _unique(page.locator('button.publish-btn').filter(
            has_text=re.compile(r"^\s*预览并发布\s*$")), "懂车号预览并发布按钮", enabled=True)
        await button.scroll_into_view_if_needed()
        await self._mark_submit(on_submit)
        await button.click(timeout=10000)
        for _ in range(12):
            if await self._has_challenge(page):
                return
            dialogs = page.locator(_DIALOGS).filter(has_text=re.compile(r"发布"))
            visible = [dialogs.nth(i) for i in range(await dialogs.count()) if await dialogs.nth(i).is_visible()]
            if len(visible) > 1:
                raise PreparationError("懂车号发布确认弹层不唯一，请核对平台记录")
            if visible:
                confirm = await _unique(visible[0].get_by_role("button", name=re.compile(
                    r"^(?:确认|确定|立即)?发布$")), "懂车号最终发布确认", enabled=True)
                await confirm.click(timeout=10000)
                return
            if (await self.read_result(page))["status"] != "unknown":
                return
            await page.wait_for_timeout(250)

    async def read_result(self, page):
        """只在提交后接受懂车号反馈；草稿与管理页跳转始终不是发表证据。"""
        if not self._submit_started:
            return {"status": "unknown", "message": "尚未提交懂车号文章；草稿保存不表示发布"}
        location = urlparse(page.url)
        if location.scheme != "https" or location.netloc != "mp.dcdapp.com":
            return {"status": "unknown", "message": "懂车号提交后页面发生变化，请核对平台内容记录"}
        result = await read_result_evidence(page, self.platform, self.title)
        # 尚无经核实的公开文章 URL/标题合同，不从管理 URL 或 ID 推导公开发表。
        if result["status"] == "published":
            return {"status": "unknown", "message": "懂车号公开文章需人工核对，请记录真实公开地址与正文依据"}
        return result
