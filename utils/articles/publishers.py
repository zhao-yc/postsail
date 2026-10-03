"""传媒平台原生文章适配；公开源码候选尚未经过真实账号验收。

入口及候选控件来源（不是线上成功证明）：
https://github.com/leaper-one/MultiPost-Extension/tree/6269ab4ada1cf661a3624b2b9f496bb032a391d5/src/sync/article
https://github.com/yjmm10/MediaSync/tree/77ec95860fd1b0898459a6f401220e34cf80f31e/packages/core/src/adapters/platforms
封面/选项要求参考蚁小二 article 文档；不能把其草稿接口当成正式发布回执：
https://github.com/yixiaoer888/yixiaoer-skill/tree/a2722c6095f57abf2e345dca637bdded44fa34df/skills/yixiaoer/references/platforms/article

未确认的控件必须停止。正文由统一剪贴板流程写入并读回，不直接替换 DOM。
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from utils.articles.browser import PreparationError, is_uploaded_image
from utils.articles.native import NativeArticleAdapter, _unique, _value


class PublisherArticleAdapter(NativeArticleAdapter):
    """只复用安全检查；每个平台保持明确的文章入口及正文候选。"""

    cover_required = False
    original_supported = False
    cover_region_selector = ""
    publish_selector = ""
    alternate_editor_locations = ()

    def _validate_destination(self, page):
        """只在公开来源确认的官方文章路径编辑，登录/其他产品跳转不算成功。"""
        actual, expected = urlparse(page.url), urlparse(self.editor_url)
        location = (actual.path.rstrip("/"), actual.fragment.split("?", 1)[0].rstrip("/"))
        expected_location = (expected.path.rstrip("/"), expected.fragment.split("?", 1)[0].rstrip("/"))
        if (actual.scheme != "https" or actual.hostname != expected.hostname or
                actual.port not in (None, 443) or actual.username or actual.password or
                location not in (expected_location, *self.alternate_editor_locations)):
            raise PreparationError(f"{self.label}已跳转离开官方文章编辑器，请检查登录或文章权限")

    async def _ensure_empty_draft(self, page, editor):
        """编辑器恢复已有草稿时保留原内容，不用新任务覆盖用户文章。"""
        title = (await _value(await self._title_field(page))).strip()
        body = re.sub(r"[\s\u200b\ufeff]+", "", await _value(editor))
        media = await editor.locator("img,video,audio,table,iframe,object,embed,hr,canvas,svg").count()
        if title or body or media:
            raise PreparationError(f"{self.label}编辑器已存在标题或正文，请先保存原草稿并打开空白文章；已阻止覆盖")

    async def open_editor(self, page):
        editor = await super().open_editor(page)
        self._validate_destination(page)
        await self._ensure_empty_draft(page, editor)
        return editor

    async def _cover_region(self, page):
        """封面必须具有独立的原生语义，不能选择整页第一个上传字段。"""
        name = re.compile(r"^(?:文章)?封面(?:图|设置|上传)?[：:]?$")
        candidates = page.get_by_role("group", name=name).or_(page.get_by_role("region", name=name))
        candidates = candidates.or_(page.locator("fieldset").filter(
            has=page.locator("legend").filter(has_text=name)))
        # 部分后台未提供 ARIA；只接受「封面」标签最近的 cover 组件，
        # 不向上寻找任意包含 file input 的 div（可能变成整个文章表单）。
        labelled = page.get_by_text(name).locator(
            "xpath=ancestor::*[(self::div or self::section) and "
            "(contains(translate(@class,'COVER','cover'),'cover') or "
            "contains(translate(@id,'COVER','cover'),'cover'))][1]")
        candidates = candidates.or_(labelled)
        if self.cover_region_selector:
            candidates = candidates.or_(page.locator(self.cover_region_selector))
        region = await _unique(candidates, f"{self.label}文章封面区域")
        if await region.locator('[contenteditable="true"],iframe').count():
            raise PreparationError(f"{self.label}封面区域与正文编辑器混合，请人工核对")
        return region

    async def _cover_images(self, page):
        region = await self._cover_region(page)
        return await region.locator("img").evaluate_all("""images => images.filter(img =>
            !img.closest('dialog,[role="dialog"],[contenteditable]')).map(img => ({
            src: img.src || '', ready: img.complete && img.naturalWidth > 0}))""")

    async def _cover_dialog(self, page):
        candidates = page.get_by_role("dialog", name=re.compile("封面|裁剪|上传图片|选择图片"))
        visible = [candidates.nth(i) for i in range(await candidates.count())
                   if await candidates.nth(i).is_visible()]
        if not visible:
            return None
        return await _unique(candidates, f"{self.label}封面上传或裁剪窗口")

    async def _preview_images(self, scope):
        return await scope.locator("img").evaluate_all("""images => images.filter(img =>
            img.complete && img.naturalWidth > 0).map(img => img.src)""")

    async def _upload_cover(self, page):
        """局限于封面组件操作；只接收新平台图片，不接受本地临时预览。"""
        region = await self._cover_region(page)
        uploads = region.locator('input[type="file"]')
        dialog = None
        previous_preview = set()
        if await uploads.count():
            upload = await _unique(uploads, f"{self.label}封面上传字段", enabled=True, visible=False)
            await upload.set_input_files(str(self.cover))
        else:
            opener = await _unique(region.get_by_role("button", name=re.compile(
                r"^(?:上传|设置|添加|选择|更换)封面(?:图)?$")), f"{self.label}封面上传入口", enabled=True)
            choosers = []
            def capture(chooser):
                choosers.append(chooser)
            page.on("filechooser", capture)
            try:
                await opener.click(timeout=10000)
                for _ in range(30):
                    dialog = await self._cover_dialog(page)
                    if choosers or dialog is not None:
                        break
                    await page.wait_for_timeout(100)
                if len(choosers) > 1 or (choosers and dialog is not None):
                    raise PreparationError(f"{self.label}封面入口产生多个上传目标，请人工核对")
                if choosers:
                    await choosers[0].set_files(str(self.cover))
                elif dialog is not None:
                    previous_preview = set(await self._preview_images(dialog))
                    upload = await _unique(dialog.locator('input[type="file"]'),
                        f"{self.label}封面窗口上传字段", enabled=True, visible=False)
                    await upload.set_input_files(str(self.cover))
                else:
                    raise PreparationError(f"未找到{self.label}封面文件选择器或上传窗口，请人工处理")
            finally:
                page.remove_listener("filechooser", capture)
        confirmed = False
        for _ in range(30):
            images = await self._cover_images(page)
            if any(is_uploaded_image(item, self.platform) and item["src"] not in self._cover_before
                   for item in images):
                return
            dialog = await self._cover_dialog(page)
            if dialog is not None and not confirmed:
                # 裁剪窗口允许本地预览；最终必须从封面组件读回平台持久 URL。
                fresh = set(await self._preview_images(dialog)) - previous_preview
                if fresh:
                    confirm = await _unique(dialog.get_by_role("button", name=re.compile(
                        r"^(?:确认|确定|完成|保存封面|确定裁剪)$")), f"{self.label}封面裁剪确认", enabled=True)
                    confirmed = True
                    await confirm.click(timeout=10000)
            await page.wait_for_timeout(500)
        raise PreparationError(f"未确认{self.label}新封面上传完成，请检查封面裁剪或上传错误；已阻止发布")

    async def _original_field(self, page):
        # 只接受原生 checkbox；普通说明文字不能证明原创设置。
        return await _unique(page.get_by_role("checkbox", name=re.compile(
            r"^(?:声明原创|申明原创|原创|个人原创)$")), f"{self.label}原创选项", enabled=True)

    async def _tag_field(self, page):
        return await _unique(page.get_by_role("textbox", name=re.compile(
            r"^(?:文章)?(?:标签|关键词|话题)$")), f"{self.label}原生文章标签输入", enabled=True)

    async def _apply_tags(self, page, editor):
        field = await self._tag_field(page)
        await field.fill(" ".join(self.tags))
        await self._verify_tags(page, editor)

    async def _verify_tags(self, page, editor):
        selected = [tag for tag in re.split(r"[\s,，]+", await _value(await self._tag_field(page))) if tag]
        if selected != self.tags:
            raise PreparationError(f"{self.label}原生标签读回不一致，已阻止发布")

    async def apply_options(self, page, editor):
        known = {"statement"} | ({"original"} if self.original_supported else set())
        unknown = {key for key, value in self.options.items()
                   if key not in known and value not in (None, "", False)}
        if unknown:
            raise PreparationError("不支持的原生文章选项：" + "、".join(sorted(unknown)))
        if self.cover_required and not self.cover:
            raise PreparationError(f"{self.label}文章需要封面，请先选择封面素材")
        if self.original_supported and "original" in self.options:
            if type(self.options["original"]) is not bool:
                raise PreparationError(f"{self.label}原创选项必须为布尔值")
            field = await self._original_field(page)
            await field.set_checked(self.options["original"])
        # 父类不识别 original，逐项执行且不改变原始选项字典。
        if self.options.get("statement"):
            await self._apply_statement(page)
        if self.tags:
            await self._apply_tags(page, editor)
        if self.cover:
            self._cover_before = {item["src"] for item in await self._cover_images(page)}
            await self._upload_cover(page)

    async def verify_options(self, page, editor):
        if self.cover_required and not self.cover:
            raise PreparationError(f"{self.label}文章需要封面，请先选择封面素材")
        if self.original_supported and "original" in self.options:
            if (await (await self._original_field(page)).is_checked()) is not self.options["original"]:
                raise PreparationError(f"{self.label}原创设置读回不一致，已阻止发布")
        await super().verify_options(page, editor)

    async def submit(self, page, on_submit):
        """原生按钮及公开脚本确认的 div 控件均须唯一、精确文案且只提交一次。"""
        if self._submit_started:
            raise PreparationError("本任务已经尝试提交，请先核对平台记录，勿重复提交")
        self._validate_destination(page)
        candidates = page.get_by_role("button", name=self.publish_name, exact=True)
        if self.publish_selector:
            # MultiPost 的 dayuhao/yidianzixun/kuaichuanhao.ts 明确使用此 div，
            # 不能假定它拥有 button role，也不能扩大成任意包含「发布」的 div。
            candidates = candidates.or_(page.locator(self.publish_selector).filter(
                has_text=re.compile(r"^\s*" + re.escape(self.publish_name) + r"\s*$")))
        button = await _unique(candidates, f"{self.label}文章发布按钮", enabled=True)
        if (await button.inner_text()).strip() != self.publish_name:
            raise PreparationError(f"{self.label}发布控件文字不一致，已阻止提交")
        if await button.evaluate("""el => el.matches(':disabled,[disabled],[aria-disabled="true"]') ||
                !!el.closest('[inert],[aria-disabled="true"]')"""):
            raise PreparationError(f"{self.label}文章发布控件尚不可用，已阻止提交")
        await button.scroll_into_view_if_needed()
        await self._mark_submit(on_submit)
        await button.click(timeout=10000)


class YidianArticleAdapter(PublisherArticleAdapter):
    """一点号富文本文章；候选来自公开脚本，仍需账号实测。"""
    platform, label = "yidian", "一点号"
    editor_url = "https://mp.yidianzixun.com/#/Writing/articleEditor"
    title_selector = "input.post-title"
    editor_selector = 'div.editor-content[contenteditable="true"]'
    publish_selector = "div.button_publish.item.editor-btn.editor-main-btn"
    cover_required = True


class DayuArticleAdapter(PublisherArticleAdapter):
    """大鱼号 UEditor 文章；跨框架定位真实可编辑 body。"""
    platform, label = "dayu", "大鱼号"
    editor_url = "https://mp.dayu.com/dashboard/article/write"
    title_selector = "input#title"
    editor_selector = "iframe#ueditor_0"
    publish_selector = "div.button_publish.item.editor-btn.editor-main-btn"
    cover_region_selector = ".article-write-article-cover_normal"

    async def open_editor(self, page):
        iframe = await NativeArticleAdapter.open_editor(self, page)
        self._validate_destination(page)
        frame = await (await iframe.element_handle()).content_frame()
        if frame is None:
            raise PreparationError("大鱼号文章编辑器框架不可读取，请检查文章权限")
        try:
            await frame.locator('body[contenteditable="true"]').wait_for(state="visible", timeout=15000)
        except Exception as exc:
            raise PreparationError("大鱼号 UEditor 正文不可编辑，请核对文章权限或页面变化") from exc
        editor = await _unique(frame.locator('body[contenteditable="true"]'), "大鱼号原生文章正文编辑器")
        await self._ensure_empty_draft(page, editor)
        return editor


class NeteaseArticleAdapter(PublisherArticleAdapter):
    """网易号 Draft.js 文章；保留新旧标题提示候选且读取实际 maxlength。"""
    platform, label = "netease", "网易号"
    editor_url = "https://mp.163.com/subscribe_v4/index.html#/article-publish"
    title_selector = ('textarea[placeholder="请输入标题 (5~64个字)"],'
                      'textarea[placeholder="请输入标题 (5~30个字)"]')
    editor_selector = '.public-DraftEditor-content[contenteditable="true"]'
    alternate_editor_locations = (("", "/article-publish"),)
    cover_required = True
    original_supported = True


class KuaichuanArticleAdapter(PublisherArticleAdapter):
    """360 快传号原生文章；不把普通视频或图文上传页视为文章编辑器。"""
    platform, label = "kuaichuan", "快传号"
    editor_url = "https://kuaichuan.360kuai.com/#/console/publish/article"
    title_selector = 'textarea[placeholder="请输入标题"]'
    editor_selector = 'div[contenteditable="true"]'
    publish_selector = "div.button_publish.item.editor-btn.editor-main-btn"
    cover_required = True
    original_supported = True


PUBLISHER_ADAPTERS = {
    "yidian": YidianArticleAdapter,
    "dayu": DayuArticleAdapter,
    "netease": NeteaseArticleAdapter,
    "kuaichuan": KuaichuanArticleAdapter,
}
