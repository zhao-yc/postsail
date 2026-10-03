"""车家号当前原生长文（真实账号上传/发布尚未验收）。

官方公开源码核实于 2026-10-03：
https://creator.autohome.com.cn/web/static/js/main.66716c76.js
T6/c2: Lexical 文章及原生剪贴板图片上传；G9/nee/T9/b9: 双封面；
kQ/sK/bG/yee: 原创、首发、条款和正式 publishType=1（草稿为 0）。
https://posterdesign.autohome.com.cn/assets/Index-Uq50sxX_.js
封面上传后自动打开美化器，原生 div.btn-cancel 保留已上传的原图。
旧 /article/post.html 已返回 404，禁止回退旧编辑器或轻文/图说入口。
"""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from PIL import Image

from utils.articles.browser import (
    PreparationError, _ContentParser, _clipboard_image, install_preview_guard, inspect_content,
    inspect_text, normalize_text, paste_rich_html, is_uploaded_image, verify_rich_structure,
)
from utils.articles.native import NativeArticleAdapter, _unique, _value
from utils.articles.model import ArticleError, validate_title_characters, weighted_character_count


class ChejiahaoArticleAdapter(NativeArticleAdapter):
    platform, label = "chejiahao", "车家号"
    editor_url = "https://creator.autohome.com.cn/web/publish/long"
    title_selector = ('input[placeholder="请输入文章标题（6-30个汉字）"],'
                      'input[placeholder="请输入文章标题(6-30个汉字)"]')
    editor_selector = '.editor-inner[data-type="article"] .editor-input[contenteditable="true"][data-lexical-editor="true"]'
    publish_selector = ".Footer_fixContainer__NYwPE.Footer_fixContainerLong__klrNM button"

    def __init__(self, snapshot, cover):
        super().__init__(snapshot, cover)
        self.option_assets = {}
        self._cover_urls: dict[str, str] = {}
        self._document = None
        self._receipt = None
        self._response_tasks = set()
        self._formal_request = None
        self._expected_json = None
        self._request_rejected = False

    def _validate_destination(self, page):
        url = urlparse(page.url)
        if (url.scheme != "https" or url.netloc != "creator.autohome.com.cn"
                or url.path != "/web/publish/long" or url.query or url.fragment):
            raise PreparationError("车家号未停留在空白原生文章入口，请检查登录、权限或旧稿地址")

    def _validate_inputs(self):
        try:
            validate_title_characters(self.platform, self.title)
        except ArticleError as exc:
            raise PreparationError(str(exc)) from exc
        allowed = {"original", "first_publish", "vertical_cover_asset_id", "links_as_text", "agree_upload_terms", "content_type"}
        unknown = [key for key, value in self.options.items()
                   if key not in allowed and value not in (None, "", False)]
        if unknown or self.tags:
            raise PreparationError("车家号暂不支持此原生选项或普通话题，请移除未支持的字段")
        for name in ("original", "first_publish", "agree_upload_terms", "links_as_text"):
            if name in self.options and type(self.options[name]) is not bool:
                raise PreparationError("车家号原创和首发选项必须为布尔值")

    async def open_editor(self, page):
        self._validate_inputs()
        if self.snapshot.get("mode") == "preview":
            await install_preview_guard(page)
        async def guard(route):
            # Official 30-second auto-save shares this endpoint. Block it so an empty
            # task cannot acquire a draft ID or update any existing platform draft.
            request = route.request
            try:
                payload = request.post_data_json
                valid = (self.snapshot.get("mode") == "publish" and self._submit_started
                         and self._formal_request is None and request.method == "POST"
                         and parse_qs(urlparse(request.url).query).get("publishType") == ["1"]
                         and self._matches_payload(payload))
            except Exception:
                valid = False
            if valid:
                self._formal_request = request
                await route.fallback()
            else:
                if self._submit_started and parse_qs(urlparse(request.url).query).get("publishType") != ["0"]:
                    self._request_rejected = True
                await route.abort("blockedbyclient")
        await page.route(re.compile(r"^https://creator\.autohome\.com\.cn/openapi/content-api/gc/article/publish(?:\?.*)?$"), guard)
        editor = await super().open_editor(page)
        self._validate_destination(page)
        if await page.evaluate("Number(localStorage.getItem('__CREATOR_NEWSONLY__'))===1"):
            raise PreparationError("此车家号账号仅能发布新闻稿，不能代替普通文章发布")
        text = re.sub(r"[\s\u200b\ufeff]+", "", await _value(editor))
        media = await editor.locator("img,video,audio,table,iframe,object,embed,hr,canvas,svg").count()
        if (await _value(await self._title_field(page))).strip() or text or media:
            raise PreparationError("车家号编辑器已有标题或正文，请先保存原草稿；已阻止覆盖")
        for orientation in ("horizontal", "vertical"):
            if await (await self._cover_region(page, orientation)).locator("img").count():
                raise PreparationError("车家号编辑器已有封面，请先保存原草稿；已阻止覆盖")
        return editor

    async def fill_title(self, page):
        self._validate_inputs()
        self._validate_destination(page)
        await super().fill_title(page)

    def _cover_file(self, orientation):
        path = self.cover if orientation == "horizontal" else self.option_assets.get("vertical_cover_asset_id")
        name = "横版" if orientation == "horizontal" else "竖版"
        if not path:
            raise PreparationError(f"车家号需要已上传的{name}封面素材")
        path = Path(path)
        width, height, ratio = (560, 420, (4, 3)) if orientation == "horizontal" else (560, 420, (3, 4))
        try:
            with Image.open(path) as image:
                actual_w, actual_h = image.size
                valid = image.format in {"JPEG", "PNG"}
            valid = (valid and actual_w >= width and actual_h >= height
                     and actual_w * ratio[1] == actual_h * ratio[0]
                     and path.stat().st_size <= 10 * 1024 * 1024)
        except (OSError, ValueError) as exc:
            raise PreparationError(f"车家号{name}封面文件不可用，请重新上传素材") from exc
        if not valid:
            raise PreparationError(f"车家号{name}封面须为 {ratio[0]}:{ratio[1]}、至少 {width}×{height}、不超过 10MiB 的 JPEG/PNG；不自动裁剪")
        return path

    @staticmethod
    def _image_key(url):
        # qL in official module 14492: image resizing and g.autoimg.cn proxy preserve
        # the asset path. Normalize only these published image transformations.
        parsed = urlparse(url if not url.startswith("//") else "https:" + url)
        host, path = parsed.netloc, parsed.path
        if host == "g.autoimg.cn" and path.startswith("/@img/"):
            host_part, _, rest = path[6:].partition("/")
            host, path = host_part + ".autoimg.cn", "/" + rest
        path = re.sub(r"/[^/]*autohomecar__", "/autohomecar__", path)
        query = "" if re.match(r"image(?:View|Mogr)2", parsed.query) else parsed.query
        return host, path, query

    @staticmethod
    def _json_signature(node):
        if not isinstance(node, dict):
            raise ValueError("invalid native body")
        keys = ("type", "text", "format", "style", "tag", "listType", "value", "start",
                "src", "width", "height", "caption", "url", "headerState", "colSpan", "rowSpan")
        return {**{key: node[key] for key in keys if key in node and node[key] not in ("", None)},
                "children": [ChejiahaoArticleAdapter._json_signature(child) for child in node.get("children", [])]}

    def _matches_payload(self, data):
        if not isinstance(data, dict) or self._expected_json is None or self._document is None:
            return False
        if (data.get("publishType") != 1 or data.get("title") != self.title
                or data.get("source") != "pc" or data.get("role") not in (2, 3)
                or any(data.get(key) not in (None, "", 0, False) for key in ("id", "draftId", "timerStatus", "isNews"))
                or data.get("coverType") != 0
                or data.get("isOriginal", 0) != int(self.options.get("original", False))
                or data.get("isFirst", 0) != int(self.options.get("first_publish", False))):
            return False
        content_type = self.options.get("content_type")
        if content_type and data.get("contentType") != (0 if content_type == "非商业内容" else 1):
            return False
        if not isinstance(data.get("imageUrls"), list) or len(data["imageUrls"]) != 1:
            return False
        if self._image_key(data["imageUrls"][0]) != self._image_key(self._cover_urls["horizontal"]):
            return False
        if self._image_key(data.get("imgVerticalUrl", "")) != self._image_key(self._cover_urls["vertical"]):
            return False
        native = json.loads(data.get("contentJson", ""))
        if self._json_signature(native.get("root")) != self._expected_json:
            return False
        class Body(_ContentParser):
            def __init__(self):
                super().__init__(); self.parts = []; self.urls = []; self.invalid = False
            def handle_starttag(self, tag, attrs):
                if tag in {"script", "iframe", "object", "embed", "form", "style"}:
                    self.invalid = True
                if tag == "img":
                    self.parts.append(f"OMNIPOSTIMAGE{len(self.urls):04d}END")
                    self.urls.append(dict(attrs).get("src", ""))
                    attrs = [(key, value) for key, value in attrs if key != "data-asset-id"] + [("data-asset-id", str(len(self.urls)))]
                super().handle_starttag(tag, attrs)
            def handle_data(self, text):
                self.parts.append(text)
                super().handle_data(text)
        body = Body(); body.feed(data.get("content", "")); body.close()
        expected = inspect_content(self._document.paste_html)
        aliases = {"b": "strong", "i": "em"}
        clean = lambda value: re.sub(r"OMNIPOSTIMAGE\d{4}END", "", normalize_text(value))
        for segment in expected.format_segments:
            if clean(segment["text"]) and not any(aliases.get(actual["tag"], actual["tag"]) == aliases.get(segment["tag"], segment["tag"])
                    and clean(actual["text"]) == clean(segment["text"]) for actual in body.format_segments):
                return False
        return (not body.invalid
                and normalize_text("".join(body.parts)) == normalize_text(inspect_text(self._document.paste_html))
                and [self._image_key(url) for url in body.urls] == [self._image_key(url) for url in self._document.uploaded_urls])

    async def _native_state(self, editor):
        try:
            state = await editor.evaluate(r"""el => {
                const api=el.__lexicalEditor;
                if(!api || typeof api.getEditorState!=='function')throw Error('missing Lexical');
                const root=api.getEditorState().toJSON().root, images=[],formats=[],types={};
                const supported=new Set(['root','paragraph','text','linebreak','heading','quote',
                    'list','listitem','link','autolink','horizontalrule','table','tablerow','tablecell','image']);
                const textOf=n=>n.type==='text'?(n.text||''):n.type==='linebreak'?'\n':
                    n.type==='image'?(n.caption||''):(n.children||[]).map(textOf).join('');
                const visit=n=>{
                    if(!supported.has(n.type))throw Error('unsupported native node '+n.type);
                    let tag=({heading:n.tag,quote:'blockquote',list:n.listType==='number'?'ol':'ul',
                        listitem:'li',link:'a',autolink:'a',horizontalrule:'hr',table:'table',
                        tablerow:'tr',tablecell:n.headerState?'th':'td'})[n.type];
                    if(tag){types[tag]=(types[tag]||0)+1;formats.push({tag,text:textOf(n)});}
                    if(n.type==='text'){
                        for(const [bit,tag] of [[1,'strong'],[2,'em'],[4,'s'],[8,'u'],[16,'code']]){
                            if(n.format&bit){types[tag]=(types[tag]||0)+1;formats.push({tag,text:n.text||''});}
                        }return n.text||'';
                    }
                    if(n.type==='image'){images.push(n);return 'OMNIPOSTIMAGE'+String(images.length-1).padStart(4,'0')+'END'+(n.caption||'');}
                    if(n.type==='linebreak')return '\n';
                    return (n.children||[]).map(visit).join('');
                };
                const sequence=visit(root),text=textOf(root),boxes=Array.from(el.querySelectorAll('.editor-image'));
                if(boxes.length!==images.length)throw Error('native image count');
                const bindings=images.map((node,index)=>{
                    const imgs=Array.from(boxes[index].querySelectorAll('img')).filter(img=>!img.closest('.editor-image-magnifier'));
                    if(imgs.length!==1||imgs[0].alt!==node.src)throw Error('native image binding');
                    return {src:node.src,ready:imgs[0].complete&&imgs[0].naturalWidth>0&&node.width>0&&node.height>0};
                });
                const clone=el.cloneNode(true);clone.querySelectorAll('.editor-image').forEach(node=>node.remove());
                const clean=value=>(value||'').replace(/[\s\u200b\ufeff]+/g,'');
                if(clean(clone.textContent)!==clean(text))throw Error('native text differs from visible body');
                return {text,sequence,images:bindings,formats,types};
            }""")
        except Exception as exc:
            raise PreparationError("车家号原生文章状态与可见正文不一致，已阻止发布") from exc
        return state

    async def read_document_state(self, editor):
        return await self._native_state(editor)

    async def verify_rich_document(self, editor, expected_html):
        await verify_rich_structure(editor, expected_html)
        state = await self._native_state(editor)
        parsed = inspect_content(expected_html)
        aliases = {"b": "strong", "i": "em"}
        clean = lambda value: re.sub(r"OMNIPOSTIMAGE\d{4}END", "", normalize_text(value))
        for segment in parsed.format_segments:
            tag = aliases.get(segment["tag"], segment["tag"])
            if clean(segment["text"]) and not any(item["tag"] == tag and
                    clean(item["text"]) == clean(segment["text"]) for item in state["formats"]):
                raise PreparationError("车家号原生保存状态未保留正文格式，已阻止发布")

    async def paste_document(self, page, editor, document):
        if inspect_content(document.paste_html).links:
            raise PreparationError("车家号原生编辑器不保留普通外链，请启用将链接转为文字和完整网址")
        await paste_rich_html(page, editor, document)
        await self.verify_rich_document(editor, document.paste_html)

    async def insert_body_images(self, page, editor, render_page, document):
        for index, (marker, path) in enumerate(zip(document.markers, document.image_paths)):
            if Path(path).stat().st_size > 10 * 1024 * 1024:
                raise PreparationError("车家号正文单图不能超过 10MiB")
            selected = await editor.evaluate("""(el,marker)=>{
                const walk=document.createTreeWalker(el,NodeFilter.SHOW_TEXT);let node;
                while(node=walk.nextNode()){const i=node.textContent.indexOf(marker);if(i<0)continue;
                    el.focus();const range=document.createRange();range.setStart(node,i);range.setEnd(node,i+marker.length);
                    const selection=window.getSelection();selection.removeAllRanges();selection.addRange(range);return true;}
                return false;
            }""", marker)
            if not selected:
                raise PreparationError("车家号正文图片定位标记丢失，已阻止发布")
            await _clipboard_image(page, render_page, path)
            await page.keyboard.press("ControlOrMeta+V")
            for _ in range(60):
                try:
                    state = await self._native_state(editor)
                    images = state["images"]
                    if (len(images) == index + 1 and all(is_uploaded_image(item, self.platform) for item in images)
                            and marker not in state["text"]):
                        if [item["src"] for item in images[:-1]] != document.uploaded_urls:
                            raise PreparationError("车家号已上传正文图片顺序变化")
                        document.uploaded_urls.append(images[-1]["src"])
                        break
                except PreparationError:
                    # Native payload and React preview update in separate frames; final verification is strict.
                    pass
                await page.wait_for_timeout(250)
            else:
                raise PreparationError("车家号正文图片未取得持久平台地址，已阻止发布")
        state = await self._native_state(editor)
        if normalize_text(state["text"]) != normalize_text(document.expected_text):
            raise PreparationError("车家号正文图片插入后全文不一致")
        if normalize_text(state["sequence"]) != normalize_text(inspect_text(document.paste_html)):
            raise PreparationError("车家号正文图片与相邻段落顺序不一致")

    async def _cover_region(self, page, orientation):
        selector = "#imageUrls.UpImageContainer_uploadBox__g2vUQ" if orientation == "horizontal" else "#imgVerticals.UpImageVericalContainer_uploadBox__ksBoL"
        return await _unique(page.locator(selector), f"车家号{orientation}封面区域")

    async def _images(self, region):
        return await region.locator("img").evaluate_all("""images => images.map(img => ({
            src:img.src || '',ready:img.complete && img.naturalWidth>0}))""")

    async def _upload_cover(self, page, orientation, path):
        region = await self._cover_region(page, orientation)
        before = {item["src"] for item in await self._images(region)}
        # 当前文章正文可能触发官方自动推荐封面，显式“替换”只针对当前空白任务。
        prefix = "UpImageContainer" if orientation == "horizontal" else "UpImageVericalContainer"
        replace = region.get_by_text("替换", exact=True)
        if await replace.count():
            opener = await _unique(replace, "车家号封面替换控件", enabled=True)
        else:
            opener = await _unique(region.locator(f'[class^="{prefix}_leftPart__"]'), "车家号封面上传空槽", enabled=True)
        await opener.click(timeout=10000)
        await page.get_by_role("dialog", name="展示封面图", exact=True).wait_for(state="visible", timeout=15000)
        dialog = await _unique(page.get_by_role("dialog", name="展示封面图", exact=True), "车家号展示封面图窗口")
        await (await _unique(dialog.get_by_role("tab", name="上传图片", exact=True), "车家号封面本地上传页签")).click()
        upload = await _unique(dialog.locator('input[type="file"][accept=".jpg,.jpeg,.png"]'),
                               "车家号封面文件字段", visible=False, enabled=True)
        previous = {item["src"] for item in await self._images(dialog)}
        await upload.set_input_files(str(path))
        for _ in range(60):
            images = [item for item in await self._images(dialog)
                      if is_uploaded_image(item, self.platform) and item["src"] not in previous]
            if images:
                break
            await page.wait_for_timeout(250)
        else:
            raise PreparationError("车家号封面文件未上传完成，请核对图片要求")
        await (await _unique(dialog.get_by_role("button", name="确定", exact=True), "车家号封面选择确认", enabled=True)).click()
        # 官方会自动打开魔方美化器；取消美化保留已选择且满足比例的原始封面。
        frame_element = page.locator('iframe[name="mofangIframe"]')
        try:
            await frame_element.wait_for(state="visible", timeout=20000)
            frame = await _unique(frame_element, "车家号封面美化窗口")
            scope = frame.content_frame
            cancel = scope.locator("div.btn-cancel").filter(has_text=re.compile(r"^取消$"))
            await cancel.wait_for(state="visible", timeout=30000)
            frame_url = await scope.locator("html").evaluate("()=>location.href")
            parsed = urlparse(frame_url)
            if parsed.scheme != "https" or parsed.netloc != "posterdesign.autohome.com.cn":
                raise PreparationError("车家号封面美化器主机不匹配")
            await (await _unique(cancel, "车家号取消封面美化", enabled=True)).click()
            await frame_element.wait_for(state="detached", timeout=10000)
        except PreparationError:
            raise
        except Exception as exc:
            raise PreparationError("车家号封面美化窗口未完成加载，不能核对本次封面") from exc
        for _ in range(60):
            current = [item for item in await self._images(region) if is_uploaded_image(item, self.platform)]
            if len(current) == 1 and current[0]["src"] not in before:
                self._cover_urls[orientation] = current[0]["src"]
                return
            await page.wait_for_timeout(250)
        raise PreparationError("车家号封面未取得新的持久平台图片地址，已阻止发布")

    async def _declaration_field(self, page, name):
        selector = "input#isOriginal" if name == "original" else "input#isFirst"
        field = await _unique(page.locator(selector), "车家号原创/首发选项", enabled=True, visible=False)
        if (await field.get_attribute("type") or "").lower() != "checkbox":
            raise PreparationError("车家号原创/首发控件类型变化")
        return field

    async def _set_declaration(self, page, name, checked):
        field = await self._declaration_field(page, name)
        if await field.is_checked() == checked:
            return
        if await field.is_visible():
            await field.set_checked(checked)
        else:
            # 原生样式可能隐藏 checkbox，只通过确切关联的可见 label 操作，
            # 不直接改 checked 或派发模拟事件绕过编辑器状态。
            control_id = "isOriginal" if name == "original" else "isFirst"
            label = await _unique(page.locator(f'label[for="{control_id}"]').or_(
                field.locator("xpath=ancestor::label[1]")), "车家号原创/首发关联标签", enabled=True)
            await label.click(timeout=10000)
        if await field.is_checked() != checked:
            raise PreparationError("车家号原创/首发设置未被原生控件接受")

    async def apply_options(self, page, editor):
        self._validate_inputs()
        files = {key: self._cover_file(key) for key in ("horizontal", "vertical")}
        self._validate_destination(page)
        # 默认不声明；原创与首发各自由用户显式布尔选项控制，不互相代填。
        if self.options.get("agree_upload_terms") is not True:
            raise PreparationError("请明确同意汽车之家内容上传服务条款和联合共创须知")
        terms = await _unique(page.locator('input#statementCheck[type="checkbox"]'), "车家号发布协议", visible=False, enabled=True)
        await terms.set_checked(True)
        content_type = self.options.get("content_type")
        group = page.locator("#contentType")
        if content_type:
            if content_type not in {"非商业内容", "商业内容"}:
                raise PreparationError("车家号内容属性选项不支持")
            await (await _unique(group.get_by_role("radio", name=content_type, exact=True), "车家号内容属性", enabled=True)).check()
        if await group.count() and not await group.locator('input[type="radio"]:checked').count():
            raise PreparationError("此车家号账号要求明确选择非商业内容或商业内容")
        for name in ("original", "first_publish"):
            await self._set_declaration(page, name, self.options.get(name, False))
        for orientation, path in files.items():
            await self._upload_cover(page, orientation, path)

    async def verify_options(self, page, editor):
        self._validate_inputs()
        self._validate_destination(page)
        if not await (await _unique(page.locator('input#statementCheck[type="checkbox"]'), "车家号发布协议", visible=False)).is_checked():
            raise PreparationError("车家号发布协议未同意")
        if self.options.get("content_type"):
            if not await (await _unique(page.locator("#contentType").get_by_role("radio", name=self.options["content_type"], exact=True), "车家号内容属性")).is_checked():
                raise PreparationError("车家号内容属性读回不一致")
        if await page.locator('input#isNews:checked').count():
            raise PreparationError("车家号当前勾选了新闻稿，不能代替普通文章发布")
        for name in ("original", "first_publish"):
            if await (await self._declaration_field(page, name)).is_checked() != self.options.get(name, False):
                raise PreparationError("车家号原创/首发设置读回不一致")
        for orientation in ("horizontal", "vertical"):
            self._cover_file(orientation)
            images = [item["src"] for item in await self._images(await self._cover_region(page, orientation))
                      if is_uploaded_image(item, self.platform)]
            if not self._cover_urls.get(orientation) or images != [self._cover_urls[orientation]]:
                raise PreparationError("车家号横/竖封面未上传完成或发生变化，已阻止发布")

    async def verify_body(self, page, editor, document):
        state = await self._native_state(editor)
        text = state["text"].strip().replace("\r", "").replace("\n", "")
        length = weighted_character_count(text)
        if not 10 <= length <= 100000:
            raise PreparationError("车家号正文须为 10–100000 个汉字等效长度（英文半字），不含图片编辑控件")
        # 统一管线已检查全文、结构、图片URL/顺序/相邻段落；提交前用同稿再检查。
        self._document = document

    async def submit(self, page, on_submit):
        if self._submit_started:
            raise PreparationError("本任务已经尝试提交，请先核对平台记录，勿重复提交")
        if self.snapshot.get("mode") == "preview" or self._document is None:
            raise PreparationError("车家号文章尚未完整准备或当前为预览模式，不能提交")
        self._validate_destination(page)
        editor = await _unique(page.locator(self.editor_selector), "车家号文章正文")
        await self.verify_title(page)
        await self.verify_options(page, editor)
        from utils.articles.adapter import _verify_final_body
        await _verify_final_body(editor, self._document, self.platform, [],
                                 document_reader=self.read_document_state, rich_verifier=self.verify_rich_document)
        button = await _unique(page.locator(self.publish_selector).filter(has_text=re.compile(r"^发布$")),
                               "车家号文章发布按钮", enabled=True)
        await button.scroll_into_view_if_needed()
        self._expected_json = self._json_signature(await editor.evaluate("el=>el.__lexicalEditor.getEditorState().toJSON().root"))

        async def capture(response):
            try:
                body = await response.json()
                if not isinstance(body, dict) or not 200 <= response.status < 300:
                    return
                code, result = body.get("returncode"), body.get("result")
                if type(code) is int and code == 0 and isinstance(result, dict):
                    identifier = result.get("id")
                    if type(identifier) in (int, str) and re.fullmatch(r"[1-9][0-9]*", str(identifier)):
                        self._receipt = {"status": "submitted", "platform_id": str(identifier),
                            "platform_status": "已提交", "message": "车家号正式文章接口确认提交，公开状态仍待核对"}
                elif type(code) is int and code != 0:
                    self._receipt = {"status": "failed", "message": "车家号正式文章接口拒绝提交，请核对平台提示"}
            except Exception:
                return

        def listen(response):
            if not self._submit_started:
                return
            try:
                url, request = urlparse(response.url), response.request
                payload = request.post_data_json
                if request != self._formal_request:
                    return
                if (url.scheme != "https" or url.netloc != "creator.autohome.com.cn"
                        or url.path != "/openapi/content-api/gc/article/publish"
                        or parse_qs(url.query).get("publishType") != ["1"]
                        or request.method != "POST" or not isinstance(payload, dict)
                        or payload.get("publishType") != 1 or payload.get("title") != self.title):
                    return
                task = asyncio.create_task(capture(response))
                self._response_tasks.add(task)
                task.add_done_callback(self._response_tasks.discard)
            except Exception:
                return
        page.on("response", listen)
        await self._mark_submit(on_submit)
        await button.click(timeout=10000)

    async def read_result(self, page):
        if self._response_tasks:
            await asyncio.gather(*tuple(self._response_tasks), return_exceptions=True)
        if self._submit_started and self._receipt:
            return self._receipt
        if self._request_rejected and self._formal_request is None:
            return {"status": "failed", "message": "车家号正式请求与已核验文章不一致，已拦截，请核对平台页面"}
        return {"status": "unknown", "message": "车家号尚无本次正式文章回执，请核对平台记录，勿重复发布"}
