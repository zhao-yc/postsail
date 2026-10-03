"""图片笔记：原图相册与纯文本独立准备，完整读回后才允许一次提交。

小红书、快手入口沿用仓库已有 Note 上传器的控件，但不调用其重试发布循环。
视频号控件参考 creatorhub 的公开实验适配（提交 c588dd58e67d，
app/platforms/channels/publish.py）；未通过真实账号验收，控件变化时停止。
"""
from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

from utils.articles.browser import (
    PreparationError, PreparedDocument, inspect_content, validate_assets,
    install_preview_guard, is_uploaded_image, read_result_evidence,
)
from utils.articles.native import NativeArticleAdapter, _unique
from utils.articles.platforms import NOTE_PLATFORMS, PLATFORMS


_RICH_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "strong", "b", "em", "i", "u", "s",
              "ul", "ol", "li", "blockquote", "table", "thead", "tbody", "tfoot", "tr", "td", "th",
              "pre", "code", "hr"}
_BLOCK_TAGS = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "pre", "tr"}


class _NoteText(HTMLParser):
    """保留段落、代码换行和完整链接；富文本语义的丢失必须明确确认。"""

    def __init__(self, preserve_whitespace=False):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.links = []
        self.rich = False
        self.in_pre = 0
        self.preserve_whitespace = preserve_whitespace

    def newline(self):
        if self.parts and not self.parts[-1].endswith("\n"):
            self.parts.append("\n")

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag in _RICH_TAGS or values.get("style"):
            self.rich = True
        if tag in _BLOCK_TAGS:
            self.newline()
        if tag == "br":
            self.parts.append("\n")
        if tag == "pre":
            self.in_pre += 1
        if tag == "a":
            self.links.append((values.get("href", ""), len(self.parts)))
        if tag == "hr":
            self.newline()
            self.parts.append("——\n")

    def handle_endtag(self, tag):
        if tag == "a" and self.links:
            href, start = self.links.pop()
            label = "".join(self.parts[start:]).strip()
            if href and href != label:
                self.parts.append(("（" + href + "）") if label else href)
        if tag == "pre":
            self.in_pre = max(0, self.in_pre - 1)
        if tag in {"td", "th"}:
            self.parts.append("\t")
        if tag in _BLOCK_TAGS:
            self.newline()

    def handle_data(self, value):
        if not self.in_pre:
            if not self.preserve_whitespace:
                value = re.sub(r"\s+", " ", value)
            if not value.strip() and (not self.parts or self.parts[-1].endswith("\n")):
                return
        self.parts.append(value)

    def text(self):
        return "\n".join(line.rstrip() for line in "".join(self.parts).splitlines()).strip()


def prepare_note_document(snapshot: dict, assets: dict) -> PreparedDocument:
    """浏览器启动前验证转换结果；封面计入相册上限且不重排已有正文图片。"""
    platform = snapshot["platform"]
    rules = PLATFORMS[platform]
    content = snapshot.get("content_html", "")
    parsed = inspect_content(content)
    validate_assets(content, assets)
    parser = _NoteText()
    parser.feed(content)
    parser.close()
    options = snapshot.get("options") or {}
    if "flatten_content" in options and type(options["flatten_content"]) is not bool:
        raise PreparationError("将富文本转换为纯文本必须为布尔值")
    if parser.rich and not options.get("flatten_content"):
        raise PreparationError(f"{rules['label']}图文笔记只支持原图相册和纯文本；请启用“将富文本转换为纯文本”后重试")
    text = parser.text()
    if platform == "kuaishou":
        # 快手现有图文表单只有描述框，标题必须明确保留为首行。
        text = snapshot["title"].strip() + (("\n" + text) if text else "")
    tags = list(dict.fromkeys(str(tag).strip().strip("#") for tag in snapshot.get("tags", [])
                             if str(tag).strip().strip("#")))
    if tags:
        text += ("\n" if text else "") + " ".join("#" + tag for tag in tags)
    if len(text) > rules["body_max_chars"]:
        raise PreparationError(f"{rules['label']}转换后正文（含网址及快手标题）最多 {rules['body_max_chars']} 字")
    ids = list(parsed.asset_ids)
    cover_id = snapshot.get("cover_asset_id")
    if cover_id and cover_id not in ids:
        ids.insert(0, cover_id)
    if not ids:
        raise PreparationError(f"{rules['label']}图文笔记至少需要一张正文图片或封面")
    if rules.get("cover_is_first_image") and cover_id and ids[0] != cover_id:
        raise PreparationError(f"{rules['label']}使用首图作为封面，请将所选封面移到正文图片首位或重新选择封面")
    if len(ids) > rules["body_max_images"]:
        raise PreparationError(f"{rules['label']}相册（含封面）最多 {rules['body_max_images']} 张图片")
    paths = []
    for asset_id in ids:
        asset = assets.get(asset_id)
        if not asset:
            raise PreparationError(f"图片素材不存在：{asset_id}")
        path = Path(asset.get("path", ""))
        if not path.is_absolute() or not path.is_file():
            raise PreparationError(f"图片素材文件不存在：{asset_id}")
        if asset.get("mime_type") not in {"image/jpeg", "image/png"}:
            raise PreparationError("图文笔记原图须为 JPEG 或 PNG，请先转换素材")
        if path.stat().st_size > rules["cover_max_bytes"]:
            raise PreparationError(f"{rules['label']}相册单张图片超过大小限制")
        if (int(asset.get("width") or 0) < rules.get("image_min_width", 0)
                or int(asset.get("height") or 0) < rules.get("image_min_height", 0)):
            raise PreparationError(f"{rules['label']}相册图片至少 {rules['image_min_width']}×{rules['image_min_height']} 像素")
        paths.append(path)
    album = "".join('<img data-asset-id="' + html.escape(asset_id, quote=True) + '">' for asset_id in ids)
    prepared = '<div data-note-album="true">' + album + '</div><p>' + html.escape(text).replace("\n", "<br>") + '</p>'
    return PreparedDocument(prepared, prepared, text, paths, [], [])


def _persistent(item: dict, platform: str) -> bool:
    return is_uploaded_image(item, platform)


def _exact_text(text: str) -> str:
    # 只规范浏览器换行和不换行空格，不吞掉正文中的空白或段落。
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ").strip()


async def _note_value(editor) -> str:
    """段落只产生语义换行，避免 innerText 把 p 的视觉间距变成重复空行。"""
    state = await editor.evaluate("el=>el.value===undefined ? {html:el.innerHTML} : {value:el.value}")
    if "value" in state:
        return state["value"]
    parser = _NoteText(preserve_whitespace=True)
    parser.feed(state["html"])
    parser.close()
    return parser.text()


class NoteAdapter(NativeArticleAdapter):
    """单张追加并核对相册；不运行旧上传器的发布循环，也不把 blob 当上传完成。"""

    async def _scope(self, page):
        return page

    async def _install_preview_guard(self, page):
        if self.snapshot.get("mode") != "preview":
            return
        await install_preview_guard(page)

    async def _open_note(self, page):
        await self._install_preview_guard(page)
        await page.goto(self.editor_url, timeout=60000, wait_until="domcontentloaded")
        if re.search(r"/(?:login|passport)(?:[/?.#]|$)", page.url, re.I):
            raise PreparationError(f"{self.label}登录已失效，请重新登录")

    async def _album_images(self, scope):
        # 未核实稳定相册容器时保守检查页面图片，只排除明确的导航与账号头像。
        # Playwright 的 img 定位器穿透开放 shadow DOM；封闭 DOM 或 blob 缩略图会明确失败。
        images = await scope.locator("img").evaluate_all("""images=>images.filter(img=>{
            if(img.closest('header,nav,[role="navigation"],[class~="avatar"],[class*="user-avatar"],'
                +'[class*="userAvatar"],[class*="user_avatar"]'))return false;
            if(/^(?:logo|网站标志)$/i.test((img.getAttribute('alt')||'').trim()))return false;
            const rect=img.getBoundingClientRect();const style=getComputedStyle(img);
            return rect.width>0&&rect.height>0&&style.visibility!=='hidden'&&style.display!=='none';
        }).map(img=>({src:img.currentSrc||img.src,ready:img.complete&&img.naturalWidth>0}))""")
        return images

    async def _upload_one(self, page, scope, path):
        upload = await _unique(scope.locator(self.upload_selector), f"{self.label}图片上传控件", visible=False)
        accept = (await upload.get_attribute("accept") or "").lower()
        if "video" in accept and not any(value in accept for value in ("image", ".jpg", ".png")):
            raise PreparationError("当前页面是视频上传控件，已阻止图文上传")
        await upload.set_input_files(str(path))

    async def _wait_uploaded(self, page, scope, document, index):
        for _ in range(60):
            if await scope.get_by_text(re.compile(r"^(?:图片)?上传失败")).filter(visible=True).count():
                raise PreparationError(f"{self.label}图片上传失败，已阻止发布")
            images = await self._album_images(scope)
            urls = [item["src"] for item in images]
            if len(urls) > index + 1 or urls[:len(document.uploaded_urls)] != document.uploaded_urls:
                raise PreparationError("平台相册图片数量或顺序异常，已阻止发布")
            if len(urls) == index + 1 and all(_persistent(item, self.platform) for item in images):
                document.uploaded_urls.append(urls[-1])
                return
            await page.wait_for_timeout(500)
        raise PreparationError(f"未确认{self.label}第 {index + 1} 张原图上传完成；本地预览不算上传凭据")

    def _body_locator(self, scope):
        return scope.locator(self.editor_selector)

    async def _body_editor(self, scope):
        body = self._body_locator(scope)
        await body.first.wait_for(state="visible", timeout=20000)
        return await _unique(body, f"{self.label}图文描述编辑器", enabled=True)

    async def _protect_existing_text(self, scope):
        """空相册不代表空草稿；上传前及正文出现后均检查，绝不覆盖已有文字。"""
        fields = [self._body_locator(scope)]
        if self.title_selector:
            fields.append(scope.locator(self.title_selector))
        for fields_locator in fields:
            for index in range(await fields_locator.count()):
                field = fields_locator.nth(index)
                if not await field.is_visible():
                    continue
                occupied = await field.evaluate("""el => Boolean(
                    String(el.value === undefined ? (el.textContent || '') : el.value).trim() ||
                    el.querySelector('img,video,audio,iframe,table,object,embed,hr,canvas,svg'))""")
                if occupied:
                    raise PreparationError(f"{self.label}页面已有标题或正文，可能存在恢复的草稿；请先清空图文表单后重试")

    def _validate_options(self):
        unsupported = [name for name, value in self.options.items()
                       if name != "flatten_content" and value not in (None, "", False)]
        if unsupported:
            raise PreparationError(f"{self.label}图文笔记尚不支持选项：" + "、".join(unsupported))

    async def prepare_note(self, page, assets):
        self._validate_options()
        document = prepare_note_document(self.snapshot, assets)
        await self._open_note(page)
        scope = await self._scope(page)
        await self._install_preview_guard(page)
        if await self._album_images(scope):
            raise PreparationError(f"{self.label}页面已有图片，可能存在恢复的草稿；请先清空图文表单后重试")
        await self._protect_existing_text(scope)
        for index, path in enumerate(document.image_paths):
            await self._upload_one(page, scope, path)
            await self._wait_uploaded(page, scope, document, index)
        editor = await self._body_editor(scope)
        await self._protect_existing_text(scope)
        await editor.fill(document.expected_text)
        if self.title_selector:
            await self.fill_title(scope)
        self._note_scope, self._note_editor, self._note_document = scope, editor, document
        await self.verify_note(page)
        return editor, document

    async def verify_note(self, page):
        scope, editor, document = self._note_scope, self._note_editor, self._note_document
        actual = _exact_text(await _note_value(editor))
        if actual != _exact_text(document.expected_text):
            raise PreparationError(f"{self.label}完整正文读回不一致，已阻止发布")
        if self.title_selector:
            await self.verify_title(scope)
        elif not actual.startswith(self.title + "\n") and document.expected_text != self.title:
            raise PreparationError(f"{self.label}描述首行标题读回不一致，已阻止发布")
        images = await self._album_images(scope)
        urls = [item["src"] for item in images]
        if (not document.uploaded_urls or urls != document.uploaded_urls or
                not all(_persistent(item, self.platform) for item in images)):
            raise PreparationError(f"{self.label}相册原图数量或顺序发生变化，已阻止发布")

    async def submit(self, page, on_submit):
        if self.snapshot.get("mode") == "preview":
            raise PreparationError("图文预览任务禁止提交")
        if self._submit_started:
            raise PreparationError("本任务已经尝试提交，请先核对平台记录，勿重复提交")
        if not getattr(self, "_note_document", None):
            raise PreparationError("图文笔记尚未完成准备，已阻止提交")
        await self.verify_note(page)
        self._receipt_before = [await read_result_evidence(scope, self.platform, self.title)
                                for scope in page.frames]
        await super().submit(self._note_scope, on_submit)

    async def read_result(self, page):
        if not self._submit_started:
            return {"status": "unknown", "message": "尚未正式提交图文，页面已有提示不能证明发布成功"}
        for scope in page.frames:
            state = await read_result_evidence(scope, self.platform, self.title)
            if state["status"] == "needs_action":
                return state
            if state["status"] != "unknown" and state not in getattr(self, "_receipt_before", []):
                return state
        return {"status": "unknown", "message": "已尝试提交图文，尚无明确平台回执；请核对平台记录，勿重复提交"}


class XiaohongshuNoteAdapter(NoteAdapter):
    platform, label = "xiaohongshu", "小红书"
    editor_url = "https://creator.xiaohongshu.com/publish/publish?from=homepage&target=image"
    title_selector = 'input[placeholder*="填写标题"]'
    editor_selector = '[contenteditable="true"]:has(p[data-placeholder*="输入正文描述"])'
    upload_selector = 'input[type="file"][accept*="image"]'


class KuaishouNoteAdapter(NoteAdapter):
    platform, label = "kuaishou", "快手"
    editor_url = "https://cp.kuaishou.com/article/publish/video"
    title_selector = ""

    async def _open_note(self, page):
        await super()._open_note(page)
        tabs = page.locator('div[role="tablist"] div[role="tab"]').filter(has_text=re.compile(r"^图文$"))
        await tabs.first.wait_for(state="visible", timeout=20000)
        await (await _unique(tabs, "快手图文标签", enabled=True)).click()

    async def _upload_one(self, page, scope, path):
        button = await _unique(scope.locator("button[class^='_upload-btn']").filter(has_text="上传图片"),
                               "快手上传图片按钮", enabled=True)
        async with page.expect_file_chooser() as pending:
            await button.click(timeout=10000)
        await (await pending.value).set_files(str(path))

    def _body_locator(self, scope):
        box = scope.get_by_text("描述", exact=True).locator("xpath=following-sibling::div")
        return box.locator('[contenteditable="true"]')


class TencentNoteAdapter(NoteAdapter):
    platform, label = "tencent", "视频号"
    editor_url = "https://channels.weixin.qq.com/platform/post/create"
    title_selector = '.short-title-wrap input'
    editor_selector = '.post-desc-box .input-editor[contenteditable="true"]'
    upload_selector = '.post-view input[type="file"]'
    publish_name = "发表"

    async def install_preparation_guard(self, page):
        """导航与正式发表名称相近；预览进入表单前禁止一切网络写请求。"""
        if self.snapshot.get("mode") != "preview" or getattr(self, "_navigation_guard", None):
            return
        self._navigation_pending = True
        self._navigation_write_blocked = False

        async def guard(route):
            if route.request.method.upper() not in {"GET", "HEAD", "OPTIONS"}:
                self._navigation_write_blocked = True
                await route.abort("blockedbyclient")
            else:
                await route.fallback()

        self._navigation_guard = guard
        await page.route("**/*", guard)

    async def _install_preview_guard(self, page):
        if not getattr(self, "_navigation_pending", False):
            await super()._install_preview_guard(page)

    @staticmethod
    def _trusted_frame(frame):
        parsed = urlparse(frame.url)
        return parsed.scheme == "https" and parsed.netloc == "channels.weixin.qq.com"

    def _check_navigation_request(self):
        if getattr(self, "_navigation_write_blocked", False):
            raise PreparationError("视频号进入图文表单时触发了写请求，预览已阻止该请求；"
                                   "请在平台核对账号、图文权限和内容记录后人工处理，不会自动重试")

    async def _unique_frame_control(self, page, text):
        found = []
        for frame in page.frames:
            if not self._trusted_frame(frame):
                continue
            locator = frame.get_by_text(text, exact=True)
            for index in range(await locator.count()):
                item = locator.nth(index)
                if await item.is_visible() and await item.is_enabled():
                    found.append(item)
        if len(found) != 1:
            raise PreparationError(f"未找到唯一的视频号“{text}”入口，请检查图文权限或页面变化")
        return found[0]

    async def _check_navigation_form(self, page, text):
        self._check_navigation_request()
        for frame in page.frames:
            if not self._trusted_frame(frame):
                continue
            await self._protect_existing_text(frame)
            if text == "发表图文":
                editors = frame.locator(self.editor_selector + "," + self.title_selector)
                if any([await editors.nth(index).is_visible() for index in range(await editors.count())]):
                    raise PreparationError("视频号已有编辑表单，不能将“发表图文”当作新建导航；请先在平台处理现有内容")

    async def _open_note(self, page):
        await self.install_preparation_guard(page)
        navigated = False
        try:
            await super()._open_note(page)
            parsed = urlparse(page.url)
            if not self._trusted_frame(page) or parsed.path != "/platform/post/create":
                raise PreparationError("未进入视频号原生创作入口，请重新登录并核对图文权限")
            # 不把现有编辑器里的同名按钮当作“新建”导航。
            for text in ("图文", "发表图文"):
                await self._check_navigation_form(page, text)
                control = None
                for _ in range(40):
                    self._check_navigation_request()
                    try:
                        control = await self._unique_frame_control(page, text)
                        break
                    except PreparationError:
                        await page.wait_for_timeout(500)
                if control is None:
                    raise PreparationError(f"未找到视频号“{text}”入口，请检查图文权限或页面变化")
                # 入口异步出现期间可能恢复旧稿，点击前必须重新核对。
                await self._check_navigation_form(page, text)
                await control.click(timeout=10000)
            await self._scope(page)
            self._check_navigation_request()
            navigated = True
        finally:
            if self.snapshot.get("mode") == "preview":
                # 先恢复完整 DOM 保护，再撤导航请求保护；错误时保留请求阻断。
                self._navigation_pending = False
                await install_preview_guard(page)
                if navigated and getattr(self, "_navigation_guard", None):
                    self._check_navigation_request()
                    await page.unroute("**/*", self._navigation_guard)

    async def _scope(self, page):
        for _ in range(40):
            self._check_navigation_request()
            found = [frame for frame in page.frames if self._trusted_frame(frame)
                     and await frame.locator(self.upload_selector).count()]
            if len(found) == 1:
                return found[0]
            if len(found) > 1:
                raise PreparationError("视频号存在多个上传表单，已阻止发布")
            await page.wait_for_timeout(500)
        raise PreparationError("未找到视频号图文上传表单，请检查账号权限")


def create_note_adapter(snapshot, cover=None):
    if snapshot["platform"] == "jd":
        from utils.articles.jd import JDNoteAdapter
        return JDNoteAdapter(snapshot, cover)
    if snapshot["platform"] == "xiaohongshu_merchant":
        from utils.articles.xiaohongshu_merchant import XiaohongshuMerchantAdapter
        return XiaohongshuMerchantAdapter(snapshot, cover)
    if snapshot["platform"] == "taobao":
        from utils.articles.taobao import TaobaoNoteAdapter
        return TaobaoNoteAdapter(snapshot, cover)
    classes = {"xiaohongshu": XiaohongshuNoteAdapter, "kuaishou": KuaishouNoteAdapter,
               "tencent": TencentNoteAdapter}
    return classes[snapshot["platform"]](snapshot, cover)
