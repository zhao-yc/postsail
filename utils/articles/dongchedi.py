"""懂车号原生文章（官方 mp/v2 PublishArticle.9031c083.js，2026-10-03）。

使用 Syl 原生剪贴板及双封面上传/编辑 UI；React 引用仅只读定位所属
ArticleStore，不写组件状态或直接请求发布 API。无真实账号发布验收。
"""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from urllib.parse import urlparse

from utils.articles.browser import (
    PreparationError, body_sequence, inspect_text, is_uploaded_image, normalize_text,
    verify_rich_structure, _clipboard_image,
)
from utils.articles.jingdong import _COMMITTED_FIBER
from utils.articles.native import NativeArticleAdapter, _unique, _value


# 官方 ArticleStore 由 React Context.Provider(value=store) 提供；编辑器与标题必须
# 属于同一 publish-editor。只读当前 committed tree，不能挑旧 alternate 的内容。
_STORE = """el=>{
 const root=el.closest('.publish-editor');if(!root)throw Error('no article root');
 let node=(""" + _COMMITTED_FIBER + """)(el);const found=new Set();
 for(let i=0;node&&i<100;i++,node=node.return){const s=node.memoizedProps&&node.memoizedProps.value;
  if(s&&s.form&&s.initInfo&&s.editor&&typeof s.editor.getHTML==='function'&&
    typeof s.editor.getText==='function'&&typeof s.editor.getExistNodes==='function'&&
    root.contains(s.editor.root))found.add(s);}
 if(found.size!==1)throw Error('no unique article store');return [...found][0];
}"""

_PUBLISH_PATH = "/motor/content_publish/publish_mp_article/v1"
_MUTATION_PATHS = {_PUBLISH_PATH, "/motor/content_publish/publish_mp_article/v2",
                   "/motor/content_publish/ad_match/pgc/solicit/upload_article"}


def _publish_request(request):
    try:
        url = urlparse(request.url)
        if (url.scheme != "https" or url.hostname != "mp.dcdapp.com" or
                url.port not in (None, 443) or url.path not in _MUTATION_PATHS):
            return False, None
        if url.path != _PUBLISH_PATH or request.method != "POST" or url.query or url.username or url.password:
            return True, None
        data = request.post_data_json
        return True, data if isinstance(data, dict) else None
    except (ValueError, TypeError, AttributeError):
        return True, None


def _submission_id(body):
    """官方 SDK 60857 解包 data，再由文章 post-hook 读取 data.pgc_id。"""
    if not isinstance(body, dict):
        return None
    status = body.get("status")
    success = type(status) is int and status == 0 or status == "success" or body.get("message") == "success"
    if not success or ("status" in body and not (type(status) is int and status == 0 or status == "success")):
        return None
    data = body.get("data")
    result = data.get("data") if isinstance(data, dict) else None
    value = result.get("pgc_id") if isinstance(result, dict) else None
    if type(value) not in (str, int):
        return None
    value = str(value)
    return value if re.fullmatch(r"[1-9][0-9]*", value) else None


class DongchediArticleAdapter(NativeArticleAdapter):
    platform, label = "dongchedi", "懂车号"
    editor_url = "https://mp.dcdapp.com/profile_v2/publish/article"
    title_selector = '.publish-editor textarea[placeholder="请输入文章标题（2～30个汉字）"]'
    editor_selector = '.publish-editor .syl-editor .ProseMirror[contenteditable="true"]'

    def __init__(self, snapshot: dict, cover: Path | None):
        super().__init__(snapshot, cover)
        self._document = None
        self._content = None
        self._covers = None
        self._allowed_request = None
        self._receipt = None
        self._response_tasks = set()
        self._receipt_event = asyncio.Event()
        self._guard_installed = False

    def _validate_destination(self, page):
        url = urlparse(page.url)
        if (url.scheme != "https" or url.hostname != "mp.dcdapp.com" or url.port not in (None, 443)
                or url.username or url.password or url.path != "/profile_v2/publish/article"
                or url.query or url.fragment):
            raise PreparationError("懂车号页面不是空白原生文章入口，已阻止覆盖旧稿或商业任务")

    async def _read_native(self, page):
        try:
            return await (await self._title_field(page)).evaluate(r"""el=>{
             const s=(""" + _STORE + r""")(el),e=s.editor,f=s.form;
             const image=x=>x?{status:x.status,uri:x.uri||'',url:x.url||'',width:x.width,height:x.height,
               ai:!!(x.meta&&x.meta.isAiCover)}:null;
             const text=e.getText()||'',nativeHTML=e.getHTML()||'';
             let html=e.getHTML({mergeEmpty:true})||'';
             const extra=e.root.querySelector('.extra-content-for-upload');if(extra)html+=extra.innerHTML;
             html=html.replace(/<span\s+typo="[^>]+?">([\w一-龥]+?)<\/span>/g,(_,x)=>x)
               .replace(/&amp;amp;/g,'&amp;').replace(/&amp;/g,'&');
             return {inited:s.inited,submitting:s.submitting,submitted:s.submitted,
               init:{pgcId:s.initInfo.pgcId,prefillId:s.initInfo.prefillId,assignProofId:s.initInfo.assignProofId,
                 juguangEdit:s.initInfo.juguangEdit,juguangType:s.initInfo.juguangType,
                 hasPrefillData:!!s.initInfo.prefillData,hasCommercialData:!!s.initInfo.juguangData},
               bind:{...s.bindInfo},title:f.title,html,text,
               textUnits:text.replace(/\s/g,'').length,htmlUnits:nativeHTML.length,
               coverType:f.coverType,covers:(f.coverList||[]).map(image),vertical:image(f.verticalCover),
               claimOrigin:f.claimOrigin,isOriginalFirst:f.isOriginalFirst,timingStatus:f.timingStatus,
               timingTime:f.timingTime,articleAdType:f.articleAdType,
               isMcn:f.isMcn,mcnRecommend:f.mcnRecommend,hotId:f.hotId,topic:f.topic,
               images:e.getExistNodes('image').map(x=>({...x.node.attrs.data})),
               cardTypes:['video','audio','search','column','pay_line','commodity','community','link','novel',
                 'phone','tweet','vote','applet','column_card','stock','comic','medical']
                 .filter(t=>e.getExistNodes(t).length)};
            }""")
        except Exception as exc:
            raise PreparationError("无法只读核实懂车号原生文章状态，请检查平台页面变化") from exc

    async def open_editor(self, page):
        await self.install_preparation_guard(page)
        editor = await super().open_editor(page)
        self._validate_destination(page)
        for _ in range(60):
            native = await self._read_native(page)
            if native["inited"]:
                break
            await page.wait_for_timeout(250)
        else:
            raise PreparationError("懂车号文章和旧稿恢复尚未完成，已停止")
        self._check_new_article(native)
        if (native["title"].strip() or normalize_text(native["text"]) or native["images"] or
                native["covers"] or native["vertical"] or native["cardTypes"] or
                normalize_text(await _value(editor)) or
                await editor.locator("img,video,audio,iframe,hr,table").count()):
            raise PreparationError("懂车号已恢复旧稿，请先保存原稿；已阻止覆盖")
        return editor

    @staticmethod
    def _check_new_article(native):
        if (not native["inited"] or native["submitted"] or any(native["init"].values()) or
                any(native["bind"].values()) or native["claimOrigin"] or native["isOriginalFirst"] or
                native["timingStatus"] or native["timingTime"] or
                any(native.get(key) for key in ("isMcn", "mcnRecommend", "hotId", "topic"))):
            raise PreparationError("懂车号存在旧稿、商业任务、原创、独家、活动或定时选项，已阻止误发")

    async def _cover_field(self, page, vertical=False):
        name = "竖版封面" if vertical else "横版封面"
        title = await _unique(page.locator('.article-publish-form .form-cell__title').filter(
            has_text=re.compile("^" + name + r"\s*(?:预览)?$")), "懂车号" + name)
        return title.locator("..")

    @staticmethod
    def _check_cover_file(path, vertical=False):
        from PIL import Image
        if not path or not path.is_file():
            raise PreparationError("懂车号需要横版和竖版两张封面")
        with Image.open(path) as image:
            width, height = image.size
            ratio, minimum = ((3, 4), (534, 712)) if vertical else ((4, 3), (532, 399))
            if (image.format not in ("JPEG", "PNG", "WEBP") or width < minimum[0] or height < minimum[1]
                    or width * ratio[1] != height * ratio[0] or path.stat().st_size > 20 * 1024 * 1024):
                raise PreparationError("懂车号封面需横版 4:3 ≥532×399、竖版 3:4 ≥534×712，JPG/PNG/WebP 各不超过20MB")
        return width, height

    async def _upload_native_cover(self, page, path, vertical=False):
        original_size = self._check_cover_file(path, vertical)
        field = await self._cover_field(page, vertical)
        upload = await _unique(field.get_by_text("上传封面", exact=True), "懂车号封面上传")
        await upload.click()
        drawer = page.locator('.image-selector-drawer')
        await drawer.first.wait_for(state="visible", timeout=10000)
        drawer = await _unique(drawer, "懂车号图片上传抽屉")
        file_input = await _unique(drawer.locator('.upload-images input[name="upfile"][type="file"]'),
                                   "懂车号封面文件", visible=False)
        await file_input.set_input_files(str(path))
        crop = page.locator('.tc-ie-base')
        await crop.first.wait_for(state="visible", timeout=30000)
        crop = await _unique(crop, "懂车号封面编辑器")
        # 官方 isSimilarSize 对等比例输入保持 needCrop=false；不移动裁剪框或缩放。
        # 官方按钮仅通过 disabled class 表示 loading/needCrop，非 HTML disabled 属性。
        done_locator = crop.locator('.footer-btns .btns .btn-sure:not(.disabled)')
        await done_locator.first.wait_for(state="visible", timeout=20000)
        done = await _unique(done_locator, "懂车号封面完成", enabled=True)
        if (await done.inner_text()).strip() != "确定":
            raise PreparationError("懂车号封面完成按钮变化")
        await done.click()
        dialog = page.locator('.arco-modal').filter(has_text="完成后无法继续编辑，是否确定完成？")
        await dialog.first.wait_for(state="visible", timeout=10000)
        dialog = await _unique(dialog, "懂车号封面完成确认")
        await (await _unique(dialog.get_by_role("button", name="确定", exact=True), "懂车号封面确认", enabled=True)).click()
        for _ in range(80):
            native = await self._read_native(page)
            images = [native["vertical"]] if vertical else native["covers"]
            if len(images) == 1 and images[0] and images[0].get("status") == 3:
                image = images[0]
                if (image["width"], image["height"]) != original_size:
                    raise PreparationError("懂车号封面编辑改变了原图尺寸，请检查裁剪结果")
                await self._verify_cover_image(page, field, image)
                return image
            await page.wait_for_timeout(500)
        raise PreparationError("懂车号封面仍在上传或结果不明确，已阻止发布")

    async def _verify_cover_image(self, page, field, expected):
        if (expected.get("status") != 3 or not expected.get("uri") or expected.get("ai") or
                not is_uploaded_image({"src": expected.get("url", ""), "ready": True}, self.platform)):
            raise PreparationError("懂车号封面尚未取得原生上传完成状态")
        # previewUrl 优先 _source，即使 DONE 也可能为 blob，不能单凭 img.src 判定。
        bound = await field.evaluate("""(el,expected)=>{
          const found=new Set();for(const element of el.querySelectorAll('img')){
            if(!element.complete||!element.naturalWidth)continue;
            let node=(""" + _COMMITTED_FIBER + """)(element);
            for(let i=0;node&&node.stateNode!==el&&i<35;i++,node=node.return){
              const image=node.memoizedProps&&node.memoizedProps.image;
              if(image&&image.status===3&&image.uri===expected.uri&&image.url===expected.url&&
                image.width===expected.width&&image.height===expected.height)found.add(image);}}
          return found.size===1;
        }""", expected)
        if not bound:
            raise PreparationError("懂车号上传状态未绑定到当前封面控件，已停止")
        decoded = await page.evaluate("""async url=>{const image=new Image();image.src=url;
          return await Promise.race([image.decode().then(()=>image.naturalWidth>0).catch(()=>false),
            new Promise(r=>setTimeout(()=>r(false),10000))]);}""", expected["url"])
        if not decoded:
            raise PreparationError("懂车号持久封面地址无法读回")

    async def apply_options(self, page, editor):
        if self._covers is not None:
            await self.verify_options(page, editor)
            return
        if self.tags or any(value not in (None, "", False) for key, value in self.options.items()
                            if key != "vertical_cover_asset_id"):
            raise PreparationError("懂车号暂仅支持竖版封面选项，不支持自由话题或其他声明")
        vertical = self.option_assets.get("vertical_cover_asset_id")
        self._check_cover_file(self.cover)
        self._check_cover_file(vertical, True)
        native = await self._read_native(page)
        self._check_new_article(native)
        if native["covers"] or native["vertical"]:
            raise PreparationError("懂车号已有封面，已阻止覆盖")
        field = await self._cover_field(page)
        radio = await _unique(field.get_by_role("radio", name="单图", exact=True), "懂车号单图封面")
        await radio.check()
        horizontal = await self._upload_native_cover(page, self.cover)
        portrait = await self._upload_native_cover(page, vertical, True)
        self._covers = (horizontal, portrait)
        self._ad_type = (await self._read_native(page)).get("articleAdType")

    async def prepare_editor(self, page):
        # 官方 Yt effect 在首张正文图完成且双封面皆空时自动生成封面。
        # 空白/旧稿检查已完成，先设置用户选定封面，使其原生 Ht 条件为 false。
        await self.apply_options(page, None)

    async def verify_options(self, page, editor):
        native = await self._read_native(page)
        self._check_new_article(native)
        if (self._covers is None or native["coverType"] != 2 or native["covers"] != [self._covers[0]] or
                native["vertical"] != self._covers[1] or native.get("articleAdType") != self._ad_type):
            raise PreparationError("懂车号双封面或选项读回不一致")
        for vertical, image in enumerate(self._covers):
            await self._verify_cover_image(page, await self._cover_field(page, bool(vertical)), image)

    async def read_document_state(self, editor):
        """Syl 的隐藏 templ 保存序列化副本，mask 才是用户可见的图片。"""
        native = await self._read_native(editor.page)
        state = await editor.evaluate(r"""el=>{
          const clone=el.cloneNode(true);
          clone.querySelectorAll('[__syl_tag="true"] > templ').forEach(node=>node.remove());
          clone.querySelectorAll('.pgc-image .pgc-img-caption-tip,.pgc-image .editor-image-menu,.pgc-image .ttcore-remove-blot')
            .forEach(node=>node.remove());
          let text='',sequence='',index=0;
          const visit=node=>{if(node.nodeType===3){text+=node.textContent;sequence+=node.textContent;return;}
            if(node.nodeType!==1)return;
            if(node.tagName==='IMG'){sequence+='OMNIPOSTIMAGE'+String(index++).padStart(4,'0')+'END';return;}
            for(const child of node.childNodes)visit(child);};visit(clone);
          const images=[...el.querySelectorAll('img')].filter(img=>!img.closest('[__syl_tag="true"] > templ'));
          return {text,sequence,images:images.map(img=>({src:img.src,ready:img.complete&&img.naturalWidth>0,
            bound:!!img.closest('mask .pgc-image .pgc-img-wrapper')}))};
        }""")
        if len(native["images"]) != len(state["images"]):
            raise PreparationError("懂车号可见正文图片数量与原生状态不一致")
        for image, data in zip(state["images"], native["images"]):
            if (not image.pop("bound") or data.get("url") != image["src"] or
                    data.get("motor_need_upload") or not data.get("uri") or
                    not data.get("naturalWidth") or not data.get("naturalHeight")):
                raise PreparationError("懂车号正文图片尚未上传或未绑定可见内容")
        return state

    async def insert_body_images(self, page, editor, render_page, document):
        """实际剪贴板图片触发官方 Syl image 插件上传；不自行调用上传接口。"""
        for index, (marker, path) in enumerate(zip(document.markers, document.image_paths)):
            selected = await editor.evaluate("""(el,marker)=>{const walker=document.createTreeWalker(el,NodeFilter.SHOW_TEXT);
              let node;while(node=walker.nextNode()){const start=node.textContent.indexOf(marker);if(start<0)continue;
                el.focus();const range=document.createRange();range.setStart(node,start);range.setEnd(node,start+marker.length);
                const selection=window.getSelection();selection.removeAllRanges();selection.addRange(range);return true;}return false;}
            """, marker)
            if not selected:
                raise PreparationError("懂车号正文图片定位标记丢失")
            await _clipboard_image(page, render_page, path)
            await page.keyboard.press("ControlOrMeta+V")
            for _ in range(60):
                try:
                    state = await self.read_document_state(editor)
                except PreparationError:
                    state = None
                if state and len(state["images"]) == index + 1 and all(
                        is_uploaded_image(image, self.platform) for image in state["images"]):
                    urls = [image["src"] for image in state["images"]]
                    if urls[:-1] != document.uploaded_urls:
                        raise PreparationError("懂车号改变了已上传正文图片的顺序")
                    document.uploaded_urls.append(urls[-1])
                    break
                await page.wait_for_timeout(500)
            else:
                raise PreparationError("懂车号正文图片上传未确认完成，已停止")
        state = await self.read_document_state(editor)
        if normalize_text(state["text"]) != normalize_text(document.expected_text):
            raise PreparationError("懂车号插图后正文内容不一致")
        if normalize_text(state["sequence"]) != normalize_text(inspect_text(document.paste_html)):
            raise PreparationError("懂车号正文图片位置与相邻段落不一致")

    async def _check_serialized(self, page, content, document):
        check_page = await page.context.new_page()
        try:
            await check_page.route("**/*", lambda route: route.abort())
            await check_page.set_content('<main id="native-article"></main>')
            target = check_page.locator('#native-article')
            await target.evaluate("(el,html)=>{el.innerHTML=html}", content)
            if await target.locator('script,style,iframe,video,audio,object,embed,form').count():
                raise PreparationError("懂车号正文出现未请求的媒体或脚本")
            if normalize_text(await body_sequence(target, include_images=False)) != normalize_text(document.expected_text):
                raise PreparationError("懂车号原生序列化正文与本次内容不一致")
            if normalize_text(await body_sequence(target)) != normalize_text(inspect_text(document.paste_html)):
                raise PreparationError("懂车号原生序列化图片位置发生变化")
            sources = await target.locator('img').evaluate_all('els=>els.map(img=>img.src)')
            if sources != document.uploaded_urls:
                raise PreparationError("懂车号原生序列化正文图片读回不一致")
            await verify_rich_structure(target, document.paste_html)
        finally:
            await check_page.close()

    async def verify_body(self, page, editor, document):
        native = await self._read_native(page)
        if native["title"] != self.title or native["cardTypes"]:
            raise PreparationError("懂车号文章包含其他内容卡片或标题不同步")
        self._check_native_limits(native)
        images = native["images"]
        if len(images) != len(document.uploaded_urls) or any(
                data.get("motor_need_upload") or not data.get("uri") or
                data.get("url") != url or not data.get("naturalWidth") or not data.get("naturalHeight")
                for data, url in zip(images, document.uploaded_urls)):
            raise PreparationError("懂车号正文图片尚未持久上传或顺序不一致")
        await self._check_serialized(page, native["html"], document)
        self._content = native["html"]
        self._document = document

    @staticmethod
    def _check_native_limits(native):
        # JS 的 length 统计 UTF-16 单元，与 Python len(astral Unicode) 不同。
        for field, maximum in (("textUnits", 50000), ("htmlUnits", 60000)):
            value = native.get(field)
            if type(value) is not int or not 0 <= value <= maximum:
                raise PreparationError("懂车号正文超过原生 50000 字或 HTML 60000 字符限制，或长度无法核实")

    def _matches_submission(self, payload):
        if not isinstance(payload, dict) or self._content is None or self._covers is None:
            return False
        if (payload.get("title") != self.title or payload.get("content") != self._content or
                type(payload.get("save")) is not int or payload["save"] != 1 or
                type(payload.get("source")) is not int or payload["source"] != 20 or
                any(payload.get(key) for key in ("pgc_id", "proof_id", "sub_task_id", "is_solicit", "ad_match_sub_task_id",
                    "is_mcn", "mcn_recommend", "hot_id", "mp_act_id", "act_id", "claim_origin", "is_original_first"))):
            return False
        extra = payload.get("extra")
        if (not isinstance(extra, dict) or type(extra.get("timer_status")) is not int or extra["timer_status"] != 0 or
                extra.get("timer_time") not in (None, "") or any(extra.get(key) for key in (
                    "is_mcn", "mcn_recommend", "hot_id", "mp_act_id", "act_id", "claim_origin", "is_original_first"))):
            return False
        horizontal, vertical = self._covers
        if extra.get("pgc_feed_covers") != [{"url": horizontal["url"], "uri": horizontal["uri"],
                "thumb_width": horizontal["width"], "thumb_height": horizontal["height"]}]:
            return False
        if extra.get("article_ad_type") != self._ad_type:
            return False
        try:
            return json.loads(extra.get("vertical_cover_image", "")) == {
                "uri": vertical["uri"], "height": vertical["height"], "width": vertical["width"], "is_ai_cover": False}
        except (ValueError, TypeError):
            return False

    async def install_preparation_guard(self, page):
        if self._guard_installed:
            return
        self._guard_installed = True

        async def guard(route):
            publication, payload = _publish_request(route.request)
            if not publication:
                return await route.fallback()
            if (self.snapshot.get("mode") != "publish" or not self._submit_started or
                    self._allowed_request is not None or not self._matches_submission(payload)):
                return await route.abort("blockedbyclient")
            self._allowed_request = route.request
            await route.fallback()
        await page.route('https://mp.dcdapp.com/**', guard)

        async def capture(response):
            try:
                if 200 <= response.status < 300:
                    article_id = _submission_id(await response.json())
                    if article_id:
                        self._receipt = {"status": "submitted", "message": "懂车号文章接口已确认提交，等待平台审核",
                                         "platform_id": article_id, "platform_status": "已提交"}
                        self._receipt_event.set()
            except Exception:
                pass

        def listen(response):
            if self._allowed_request is not None and response.request == self._allowed_request:
                task = asyncio.create_task(capture(response))
                self._response_tasks.add(task)
                task.add_done_callback(self._response_tasks.discard)
        page.on("response", listen)

    async def submit(self, page, on_submit):
        self._validate_destination(page)
        if self.snapshot.get("mode") != "publish" or self._document is None:
            raise PreparationError("懂车号当前是预览模式或尚未准备完成")
        editor = await _unique(page.locator(self.editor_selector), "懂车号文章正文")
        await self.verify_title(page)
        await self.verify_options(page, editor)
        await self.verify_body(page, editor, self._document)
        button = await _unique(page.get_by_role("button", name="发布", exact=True), "懂车号文章发布", enabled=True)
        await button.scroll_into_view_if_needed()
        await self._mark_submit(on_submit)
        await button.click(timeout=10000)
        # 原生发布只点一次；随后仅处理两种源码已确认的可选确认。
        handled = set()
        for _ in range(60):
            if self._allowed_request is not None:
                return
            dialogs = page.locator('.arco-modal:visible')
            for index in range(await dialogs.count()):
                dialog = dialogs.nth(index)
                heading = dialog.locator('.arco-modal-title')
                if await heading.count() != 1:
                    continue
                title = (await heading.inner_text()).strip()
                text = await dialog.inner_text()
                if title == "作品同步授权" and title not in handled:
                    if await dialog.get_by_role('checkbox').is_checked():
                        raise PreparationError("懂车号同步授权包含永久偏好，已停止")
                    await (await _unique(dialog.locator('.arco-modal-close-icon'), "懂车号拒绝作品同步授权")).click()
                    handled.add(title)
                elif title == "提示" and "该文章选择了“不投放广告”，将不会产生广告收益。" in text and "ad" not in handled:
                    await (await _unique(dialog.get_by_role('button', name="确定", exact=True), "懂车号保持不投放广告")).click()
                    handled.add("ad")
            await page.wait_for_timeout(250)

    async def read_result(self, page):
        if self._response_tasks:
            await asyncio.wait(set(self._response_tasks), timeout=2)
        if self._allowed_request is not None and self._receipt is None:
            try:
                await asyncio.wait_for(self._receipt_event.wait(), timeout=.5)
            except asyncio.TimeoutError:
                pass
        return dict(self._receipt) if self._receipt else {
            "status": "unknown", "message": "尚未取得懂车号明确文章提交回执，请核对平台记录，勿重复提交"}
