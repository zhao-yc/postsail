"""京东创作服务平台的原生文章（不是发布图文）。

依据 2026-10-01 京东公开前端：talent-platform-new/1790145277602 的
main-Buzi2ykr.js、index-CdTwnNcS.js、jdr-CPwuq2e9.js、index-CtzUM7Yv.js。
根地址 https://storage.360buyimg.com/ifloors/。尚未经过真实账号发文验收。

京东主动剥离剪贴板格式，且 Braft 默认粘图仅生成内联图片。因此正文使用
编辑器公开 createEditorState/setValue API，图片仍经过原生上传及裁剪窗口。
React 引用仅用于只读定位所属组件，不写 fiber、DOM 或组件私有 state。
"""
from __future__ import annotations

import asyncio
import html
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from utils.articles.browser import (
    PreparationError, inspect_content, inspect_text, is_uploaded_image, normalize_text, verify_rich_structure,
)
from utils.articles.native import NativeArticleAdapter, _unique, _value


def _native_text(content):
    """原生 HTML 已使用平台 URL，不再具有应用素材 ID；只读提取其文本。"""
    class Reader(HTMLParser):
        def handle_data(self, data):
            self.parts.append(data)
    reader = Reader(convert_charrefs=True)
    reader.parts = []
    reader.feed(content)
    reader.close()
    return "".join(reader.parts)


_COMMITTED_FIBER = """el=>{
    const key=Object.keys(el).find(k=>k.startsWith('__reactFiber$')||k.startsWith('__reactInternalInstance$'));
    let root=key&&el[key];if(!root)return null;
    while(root.return)root=root.return;
    const current=root.stateNode&&root.stateNode.current;if(!current)return null;
    const pending=[current];for(let i=0;pending.length&&i<30000;i++){
        const node=pending.pop();if(node.stateNode===el)return node;
        if(node.sibling)pending.push(node.sibling);if(node.child)pending.push(node.child);}
    return null;
}"""


# 从正文 DOM 向上只读寻找所属 RichTextEditor；不依赖压缩类名，不扫描其他编辑器。
_EDITOR_API = """el => {
    let node=(""" + _COMMITTED_FIBER + """)(el); const found=new Set();
    for(let i=0;node&&i<100;i++,node=node.return){const instance=node.stateNode;
        if(instance&&typeof instance.getEditorInstance==='function'&&
           typeof instance.getRteContents==='function')found.add(instance);}
    if(found.size!==1)throw Error('未找到唯一的京东原生编辑器实例');
    const wrapper=[...found][0], editor=wrapper.getEditorInstance();
    if(!editor||typeof editor.getValue!=='function'||typeof editor.setValue!=='function'||
        typeof editor.constructor.createEditorState!=='function'||typeof editor.props.onChange!=='function')
        throw Error('京东编辑器公开 API 已变化');
    return {wrapper,editor};
}"""


def _publish_request(request) -> tuple[bool, dict | None]:
    """识别官方原生提交；JSON 是 URL encoded 表单的 body 字段。"""
    try:
        parsed = urlparse(request.url)
        if parsed.scheme != "https" or parsed.hostname != "api.m.jd.com" or parsed.port not in (None, 443):
            return False, None
        query = parse_qs(parsed.query)
        form = parse_qs(request.post_data or "")
        publication = (parsed.path.rstrip("/") == "/articleSavePublish" or
                       "articleSavePublish" in query.get("functionId", []) + form.get("functionId", []))
        if not publication:
            return False, None
        if request.method != "POST" or len(form.get("body", [])) != 1:
            return True, None
        body = json.loads(form["body"][0])
        return True, body if isinstance(body, dict) else None
    except (ValueError, TypeError, AttributeError):
        return True, None


def _submission_id(body) -> str | None:
    """复现官方 SDK 的明确成功条件，并拒绝成功字段互相矛盾的响应。"""
    if not isinstance(body, dict):
        return None
    success = (body.get("success") is True or body.get("isSuccess") is True or
               type(body.get("result_code")) is int and body["result_code"] == 0 or
               body.get("resultCode") == "0" or body.get("busiCode") == "0")
    if not success or any(body.get(key) is False for key in ("success", "isSuccess")):
        return None
    for key in ("result_code", "resultCode", "busiCode", "code", "status"):
        if key in body and (type(body[key]) is bool or body[key] not in (None, 0, "0")):
            return None
    value = body.get("data", body.get("result"))
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    value = str(value)
    return value if re.fullmatch(r"[1-9][0-9]*", value) else None


class JingdongArticleAdapter(NativeArticleAdapter):
    platform, label = "jingdong", "京东"
    editor_url = "https://dr.jd.com/n/publish-article.html"
    root_selector = '.dr-publish-article-wrapper[data-spm-c="c00009560"]'
    title_selector = root_selector + ' .dr-create-form input#title'
    editor_selector = root_selector + ' #module-richtextNew #richtext-editor-box .public-DraftEditor-content[contenteditable="true"]'
    publish_selector = root_selector + ' .page-footer [data-spm-click="publishArticleSubmit"]'
    cover_items = root_selector + ' .article-imageArea .dr-upload-image-component .file-item:not(.btn-upload)'

    def __init__(self, snapshot: dict, cover: Path | None):
        super().__init__(snapshot, cover)
        self._description_data = None
        self._document = None
        self._allowed_request = None
        self._receipt = None
        self._response_tasks = set()
        self._receipt_event = asyncio.Event()
        self._category_path_key = None
        self._selected_tags = []

    def _validate_destination(self, page):
        url = urlparse(page.url)
        if (url.scheme != "https" or url.hostname != "dr.jd.com" or url.port not in (None, 443)
                or url.username or url.password or url.path != "/n/publish-article.html"
                or url.fragment or any(parse_qs(url.query).get("id", []))):
            raise PreparationError("京东页面不是空白原生文章入口，已阻止覆盖或误发")

    async def open_editor(self, page):
        editor = await super().open_editor(page)
        self._validate_destination(page)
        native = await self._read_native(editor)
        if ((await _value(await self._title_field(page))).strip() or
                normalize_text(await _value(editor)) or native["text"].strip() or
                not native["empty"] or await editor.locator("img,video,audio,table,iframe,hr").count()):
            raise PreparationError("京东编辑器已恢复旧稿，请先保存原稿；已阻止覆盖")
        return editor

    async def _read_native(self, editor):
        try:
            return await editor.evaluate("""el=>{const {wrapper,editor}=(""" + _EDITOR_API + """)(el);
                const value=editor.getValue(), content=wrapper.getRteContents();
                return {html:value.toHTML(),text:value.toText(),data:content.rteData,empty:content.isEmpty};} """)
        except Exception as exc:
            raise PreparationError("无法读回京东原生正文状态，请检查平台编辑器变化") from exc

    async def verify_rich_document(self, editor, expected_html):
        """Draft 可见行内格式用 span；核验其官方 HTML 序列化，不改正文 DOM。"""
        native = await self._read_native(editor)
        serialized_html = self._serialized_html(native["data"])
        check_page = await editor.page.context.new_page()
        try:
            await check_page.route("**/*", lambda route: route.abort())
            await check_page.set_content("<main id='native-article'></main>")
            await check_page.locator("#native-article").evaluate("(el,html)=>{el.innerHTML=html}", serialized_html)
            await verify_rich_structure(check_page.locator("#native-article"), expected_html)
        finally:
            await check_page.close()

    async def paste_document(self, page, editor, document):
        """公开受控编辑器 API 导入，保留官方 onChange→表单同步。"""
        if inspect_content(document.paste_html).links:
            await _unique(page.locator(self.root_selector + ' #richtext-editor-box li.hyperlink-icon[title="超链接"]'),
                          "京东原生超链接工具（当前账号可能没有权限）")
        try:
            await editor.evaluate("""(el,html)=>{const {editor}=(""" + _EDITOR_API + """)(el);
                const state=editor.constructor.createEditorState(html,{...editor.props.converts,editorId:editor.props.id});
                editor.setValue(state);} """, document.paste_html)
        except Exception as exc:
            raise PreparationError("京东原生编辑器未接受正文导入，已阻止发布") from exc
        await page.wait_for_timeout(750)  # 官方 FormItemRichText 的 onChange 防抖为 600ms。
        if normalize_text(await _value(editor)) != normalize_text(inspect_text(document.paste_html)):
            raise PreparationError("京东正文导入后可见文字读回不一致")
        native = await self._read_native(editor)
        if normalize_text(inspect_text(self._serialized_html(native["data"]))) != normalize_text(inspect_text(document.paste_html)):
            raise PreparationError("京东原生序列化改变了正文文字，已阻止发布")
        await self.verify_rich_document(editor, document.paste_html)

    async def _full_image_crop(self, modal):
        """通过 Cropper 公开 API 恢复全图，防止其默认 80% 裁剪损失正文。"""
        for _ in range(40):
            result = await modal.evaluate("""el=>{const candidates=[...el.querySelectorAll('img')]
                .filter(img=>img.cropper&&typeof img.cropper.getImageData==='function');
                if(candidates.length!==1)return false;
                const cropper=candidates[0].cropper,image=cropper.getImageData();
                if(!image.naturalWidth||!image.naturalHeight)return false;
                cropper.setData({x:0,y:0,width:image.naturalWidth,height:image.naturalHeight});
                const data=cropper.getData();return Math.abs(data.x)<1&&Math.abs(data.y)<1&&
                    Math.abs(data.width-image.naturalWidth)<1&&Math.abs(data.height-image.naturalHeight)<1;
            }""")
            if result:
                return
            await modal.page.wait_for_timeout(100)
        raise PreparationError("未能确认京东正文图片完整裁剪区域，已阻止丢图发布")

    async def _leave_body_hover(self, page):
        # Braft 鼠标悬停图片时临时设置正文 contenteditable=false，并显示原生工具栏。
        field = await self._title_field(page)
        box = await field.bounding_box()
        if box:
            await page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        await page.locator(self.editor_selector).first.wait_for(state="visible", timeout=10000)

    async def insert_body_images(self, page, editor, render_page, document):
        from PIL import Image
        for index, (marker, path) in enumerate(zip(document.markers, document.image_paths)):
            with Image.open(path) as image:
                if image.format == "GIF" or min(image.size) < 300 or path.stat().st_size > 5 * 1024 * 1024:
                    raise PreparationError("京东正文图片需至少 300×300、最大 5MB，且不支持 GIF；请调整素材或分段图")
            selected = await editor.evaluate("""(el,marker)=>{const walk=document.createTreeWalker(el,NodeFilter.SHOW_TEXT);
                let node;while(node=walk.nextNode()){const start=node.textContent.indexOf(marker);if(start<0)continue;
                    el.focus();const range=document.createRange();range.setStart(node,start);range.setEnd(node,start+marker.length);
                    const selection=window.getSelection();selection.removeAllRanges();selection.addRange(range);return true;}return false;}""", marker)
            if not selected:
                raise PreparationError("京东正文图片定位标记丢失")
            await page.keyboard.press("Backspace")
            if marker in await _value(editor):
                raise PreparationError("京东编辑器未同步图片插入位置")
            upload = await _unique(page.locator(self.root_selector +
                ' #module-richtextNew #richtext-editor-box li.image-icon #rte-cutupload-box input.image-cut-input[type="file"]'),
                "京东正文图片上传字段", enabled=True, visible=False)
            await upload.set_input_files(str(path))
            dialogs = page.locator(self.root_selector + ' #rte-cutupload-box .rte-modal:not(.rte-modal-hide)')
            await dialogs.first.wait_for(state="visible", timeout=10000)
            modal = await _unique(dialogs, "京东编辑图片窗口")
            if (await modal.locator('.jd-modal-title').inner_text()).strip() != "编辑图片":
                raise PreparationError("京东正文图片窗口名称变化")
            jump = modal.locator('input[name="imgJump"]')
            if await jump.count() and (await _value(jump)).strip():
                raise PreparationError("京东正文图片携带未请求的跳转链接")
            await self._full_image_crop(modal)
            button = await _unique(modal.locator('.commonHandleBtns input.ui-btn-blue[type="button"][value="上传"]'),
                                   "京东正文图片上传确认", enabled=True)
            await button.click()
            await self._leave_body_hover(page)
            for _ in range(50):
                images = await editor.locator("img").evaluate_all("els=>els.map(img=>({src:img.src,ready:img.complete&&img.naturalWidth>0}))")
                if (len(images) == index + 1 and all(is_uploaded_image(item, self.platform) for item in images)):
                    if [item["src"] for item in images[:-1]] != document.uploaded_urls:
                        raise PreparationError("京东已上传正文图片顺序变化")
                    document.uploaded_urls.append(images[-1]["src"])
                    break
                await page.wait_for_timeout(400)
            else:
                raise PreparationError("京东原生正文图片上传未确认完成")
        if document.image_paths:
            await self._leave_body_hover(page)
            await page.wait_for_timeout(750)
        self._document = document

    async def _cover_images(self, page):
        # 官方预览保留已 revoke 的 blobImg，甚至替换成错误占位图；必须读该上传项 file.img。
        return await page.locator(self.cover_items).evaluate_all(r"""async items=>Promise.all(items.map(async el=>{
            if(el.querySelector('.upload-status')||!el.querySelector('.image-edit-wrapper'))return {src:'',ready:false};
            let fiber=(""" + _COMMITTED_FIBER + r""")(el),file;for(let i=0;fiber&&i<12;i++,fiber=fiber.return){
                if(fiber.memoizedProps&&fiber.memoizedProps.file){file=fiber.memoizedProps.file;break;}}
            const src=file&&!file.error&&file.img||'';if(!/^https?:\/\//.test(src))return {src,ready:false};
            const img=new Image();img.src=src;let ready=false;
            try{await Promise.race([img.decode(),new Promise((_,reject)=>setTimeout(()=>reject(Error('timeout')),5000))]);
                ready=img.naturalWidth>0;}catch{}return {src,ready};}));""")

    async def _upload_cover(self, page):
        if await page.locator(self.cover_items).count():
            raise PreparationError("京东文章已有封面，请核对原稿，已阻止覆盖")
        opener = await _unique(page.locator(self.root_selector +
            ' .article-imageArea .dr-upload-image-component .file-item.btn-upload'), "京东文章封面入口", enabled=True)
        async with page.expect_file_chooser() as event:
            await opener.click()
        await (await event.value).set_files(str(self.cover))
        candidates = page.get_by_role("dialog", name="图片裁剪", exact=True)
        await candidates.first.wait_for(state="visible", timeout=10000)
        modal = await _unique(candidates, "京东封面裁剪窗口")
        preview = await _unique(modal.locator('.image-cut-modal-body .crop-image img'), "京东封面裁剪预览")
        await preview.evaluate("img=>img.decode()")
        await page.wait_for_timeout(300)
        button = await _unique(modal.get_by_role("button", name="确定", exact=True), "京东封面裁剪确认", enabled=True)
        await button.click()
        await self._wait_cover_changed(page)
        images = await self._cover_images(page)
        if len(images) != 1:
            raise PreparationError("京东封面上传数量不一致")
        self._cover_url = images[0]["src"]

    async def _apply_category(self, page):
        path = [item.strip() for item in str(self.options["category"]).split("/")]
        if len(path) != 3 or any(not item for item in path):
            raise PreparationError("京东标签分类必须填写完整的一级/二级/三级路径")
        container = await _unique(page.locator(self.root_selector + ' .article-tags .publish-select-tags .tag-select-container'),
                                  "京东文章三级标签")
        await container.click()
        for index, name in enumerate(path):
            visible = []
            for _ in range(60):
                menus = page.get_by_role("menu")
                visible = [menus.nth(i) for i in range(await menus.count()) if await menus.nth(i).is_visible()]
                if len(visible) == index + 1 and await visible[index].get_by_role("menuitemcheckbox").count():
                    break
                await page.wait_for_timeout(150)
            else:
                raise PreparationError("京东标签级联菜单层级不明确")
            items = visible[index].get_by_role("menuitemcheckbox")
            matches = [items.nth(i) for i in range(await items.count())
                       if await items.nth(i).get_attribute("title") == name]
            if len(matches) != 1:
                raise PreparationError("未找到唯一的京东标签选项")
            item = matches[0]
            # title 是官方 Cascader 对完整 label 的原生属性，避免重名/截断文本匹配。
            if await item.get_attribute("title") != name:
                raise PreparationError("京东标签选项读回不一致")
            if index < 2:
                await item.hover()
            else:
                await item.click()
                if await item.get_attribute("aria-checked") != "true":
                    raise PreparationError("京东三级标签未选中")
                self._category_path_key = await item.get_attribute("data-path-key")
                if not self._category_path_key:
                    raise PreparationError("京东三级标签缺少完整路径证据")
        await page.keyboard.press("Escape")
        self._selected_tags = await self._native_tags(page)
        if len(self._selected_tags) != 1 or self._selected_tags[0].get("name") != path[2]:
            raise PreparationError("京东三级标签未同步到原生表单状态")

    async def _native_tags(self, page):
        container = page.locator(self.root_selector + ' .article-tags .publish-select-tags .tag-select-container')
        if not await container.count():
            return []
        field = await _unique(container.get_by_role("combobox"), "京东原生标签选择器")
        result = await field.evaluate("""el=>{
            let node=(""" + _COMMITTED_FIBER + """)(el);for(let i=0;node&&i<60;i++,node=node.return){const p=node.memoizedProps;
                if(!p||!p.multipleOnlyLeaf||!p.multiple||!Array.isArray(p.options)||!Array.isArray(p.value))continue;
                return p.value.map(path=>{if(!Array.isArray(path)||path.length!==3)throw Error('标签不是三级路径');
                    let options=p.options,leaf;for(const id of path){const found=options.filter(o=>o.value===id);
                        if(found.length!==1)throw Error('标签路径不唯一');leaf=found[0];options=leaf.children||[];}
                    return {id:leaf.value,name:leaf.label||'',thirdClassifyId:leaf.thirdClassifyId,
                        secondClassifyId:leaf.secondClassifyId};});}throw Error('无法读回原生标签状态');}""")
        if not isinstance(result, list):
            raise PreparationError("京东原生标签状态读回失败")
        return result

    async def apply_options(self, page, editor):
        unknown = [key for key, value in self.options.items() if key != "category" and value not in (None, "", False)]
        if unknown or self.tags:
            raise PreparationError("京东仅支持原生三级标签分类选项，请移除未支持的选项或自由话题")
        if not self.cover:
            raise PreparationError("京东文章需要封面，请先选择封面素材")
        if await page.locator(self.root_selector + ' .article-contentType').count():
            raise PreparationError("京东当前频道要求额外的文章类型，请在平台人工设置")
        if self.options.get("category"):
            await self._apply_category(page)
        self._cover_before = set()
        await self._upload_cover(page)

    async def verify_options(self, page, editor):
        await self._leave_body_hover(page)
        images = await self._cover_images(page)
        if (len(images) != 1 or not is_uploaded_image(images[0], self.platform)
                or images[0]["src"] != getattr(self, "_cover_url", None)):
            raise PreparationError("京东文章封面未完成上传或发生变化")
        if await self._native_tags(page) != self._selected_tags:
            raise PreparationError("京东已选三级标签路径读回不一致")

    async def verify_body(self, page, editor, document):
        native = await self._read_native(editor)
        # Braft .toText() 为 atomic 图片返回占位字符 a；官方 HTML 的可见文字才是正文。
        if normalize_text(_native_text(native["html"])) != normalize_text(document.expected_text):
            raise PreparationError("京东正文可见内容与原生提交状态不一致")
        data = native["data"]
        if not isinstance(data, list) or not data or any(not isinstance(item, dict) or type(item.get("type")) is not int or item["type"] not in (1, 2) for item in data):
            raise PreparationError("京东文章原生序列化包含未支持的内容")
        text = "".join(inspect_text(item.get("content", "")) for item in data if item["type"] == 1)
        urls = [item.get("content") for item in data if item["type"] == 2]
        if normalize_text(text) != normalize_text(document.expected_text) or urls != document.uploaded_urls:
            raise PreparationError("京东文章提交正文或图片与本次内容不一致")
        # 原生 serializer 会单独处理媒体和转义文本；逐块核验位置，不能只比总字数。
        sequence, image_index = [], 0
        for item in data:
            if item["type"] == 1:
                sequence.append(inspect_text(item.get("content", "")))
            else:
                sequence.append(document.markers[image_index])
                image_index += 1
        if normalize_text("".join(sequence)) != normalize_text(inspect_text(document.paste_html)):
            raise PreparationError("京东提交正文中图片与相邻段落的位置发生变化")
        await self.verify_rich_document(editor, document.paste_html)
        self._description_data = data
        self._document = document

    @staticmethod
    def _serialized_html(data):
        if not isinstance(data, list):
            raise PreparationError("京东原生正文序列化结构不明确")
        parts = []
        for item in data:
            if not isinstance(item, dict) or type(item.get("type")) is not int or not isinstance(item.get("content"), str):
                raise PreparationError("京东原生正文序列化结构不明确")
            if item.get("type") == 1:
                if re.search(r"<\s*(?:img|script|style|iframe|object|embed|form)\b|\son\w+\s*=", item["content"], re.I):
                    raise PreparationError("京东原生正文包含未支持的内容")
                parts.append(item["content"])
            elif item.get("type") == 2 and is_uploaded_image({"src": item["content"], "ready": True}, "jingdong"):
                parts.append('<img data-asset-id="native" src="' + html.escape(item["content"], quote=True) + '">')
            else:
                raise PreparationError("京东原生正文包含未支持的卡片或未上传图片")
        return "".join(parts)

    def _matches_submission(self, payload):
        if not isinstance(payload, dict) or self._description_data is None:
            return False
        style = payload.get("style")
        if payload.get("title") != self.title or not (type(style) is int and style == 0 or style == "0") or payload.get("id"):
            return False
        if (payload.get("indexImage") != [getattr(self, "_cover_url", None)] or
                payload.get("tags") != self._selected_tags):
            return False
        try:
            return json.loads(payload.get("descriptionStr", "")) == self._description_data
        except (TypeError, ValueError):
            return False

    async def install_preparation_guard(self, page):
        async def guard(route):
            url = urlparse(route.request.url)
            form = parse_qs(route.request.post_data or "")
            if (self.snapshot.get("mode") == "preview" and (url.path.rstrip("/") == "/articleSaveDraft" or
                    "articleSaveDraft" in parse_qs(url.query).get("functionId", []) + form.get("functionId", []))):
                return await route.abort("blockedbyclient")
            publication, payload = _publish_request(route.request)
            if not publication:
                return await route.fallback()
            if (self.snapshot.get("mode") != "publish" or not self._submit_started or
                    self._allowed_request is not None or not self._matches_submission(payload)):
                return await route.abort("blockedbyclient")
            self._allowed_request = route.request
            await route.fallback()
        await page.route("https://api.m.jd.com/**", guard)

        async def capture(response):
            try:
                if 200 <= response.status < 300:
                    article_id = _submission_id(await response.json())
                    if article_id:
                        self._receipt = {"status": "submitted", "message": "京东文章提交接口已确认成功，等待平台审核",
                                         "platform_id": article_id, "platform_status": "待审核"}
                        self._receipt_event.set()
            except Exception:
                pass  # 未知回执保留 unknown，不根据跳转/HTTP 成功推测文章状态。

        def listen(response):
            if self._allowed_request is not None and response.request == self._allowed_request:
                task = asyncio.create_task(capture(response))
                self._response_tasks.add(task)
                task.add_done_callback(self._response_tasks.discard)
        page.on("response", listen)

    async def submit(self, page, on_submit):
        self._validate_destination(page)
        if self.snapshot.get("mode") != "publish" or self._document is None:
            raise PreparationError("京东文章尚未准备完成或当前是预览模式")
        await self._leave_body_hover(page)
        editor = await _unique(page.locator(self.editor_selector), "京东文章正文")
        await self.verify_title(page)
        await self.verify_options(page, editor)
        await self.verify_body(page, editor, self._document)
        button = await _unique(page.locator(self.publish_selector), "京东文章发布按钮", enabled=True)
        if (await button.inner_text()).strip() != "发布":
            raise PreparationError("京东文章发布控件变化")
        await button.scroll_into_view_if_needed()
        await self._mark_submit(on_submit)
        await button.click(timeout=10000)

    async def read_result(self, page):
        if self._response_tasks:
            await asyncio.wait(set(self._response_tasks), timeout=2)
        if self._allowed_request is not None and self._receipt is None:
            try:
                await asyncio.wait_for(self._receipt_event.wait(), timeout=.5)
            except asyncio.TimeoutError:
                pass
        return dict(self._receipt) if self._receipt else {
            "status": "unknown", "message": "尚未取得京东文章明确提交回执，请核对平台记录，勿重复提交"}
