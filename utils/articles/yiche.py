"""易车号原生文章，依据 2026-10-03 官方公开 Nuxt 资源。

https://mp.yiche.com/article/index-new
https://mp.yiche.com/_nuxt/6657c87.js (Article、Quill、双封面)
https://mp.yiche.com/_nuxt/49f3426.js (API 地址及 param 请求封装)

原生 DOM 显示服务器返回的 imgBase64，提交正文及封面使用 imgKey。
因此必须将本次文件、真正上传响应、DOM 和提交载荷相互绑定，不能把
data URL 本身视为上传成功。仅操作原生控件及已公开的 VueCropper API；
Vue 引用只用于读取文章状态和定位裁剪组件。不代表真实账号验收。
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import re
from email.parser import BytesParser
from email.policy import default as email_policy
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image

from utils.articles.browser import (
    PreparationError, _clipboard_image, body_sequence, inspect_text,
    normalize_text, verify_rich_structure,
)
from utils.articles.native import NativeArticleAdapter, _unique, _value


UPLOAD_URL = "https://mp.yiche.com/api/upload_image/mp_real_upload"
SAVE_URL = "https://mp.yiche.com/web_mp/api/v1/pub/savenews"
DECLARATIONS = {"内容无需标注": 0, "含AI生成内容": 1, "含虚构演绎内容": 2,
                "内容含营销信息": 3, "个人观点，仅供参考": 5, "内容为转载": 4}
# 官方 Article 以及 onlyHeader 使用的 POST 只读接口；未知写入一律阻断。
READ_POST_PATHS = frozenset({
    "/web_mp/api/v1/home/userinfo", "/web_mp/api/v1/manage/newslist",
    "/web_mp/api/v1/pub/news_white_flag", "/web_mp/api/v1/pub/news_category_list",
    "/web_mp/api/v1/pub/get_available_activity", "/web_mp/api/v1/pub/hot_topic_list",
    "/web_mp/api/v1/pub/photoquery", "/web_mp/api/v1/author/programs",
    "/web_mp/api/v1/business/get_vote_list", "/web_mp/api/v1/auth/real/get_auth_status",
    "/web_mp/api/v1/auth/need_copy_popup",
})


def _endpoint(url, expected):
    try:
        parsed, target = urlparse(url), urlparse(expected)
        return (parsed.scheme == "https" and parsed.hostname == target.hostname
                and parsed.port in (None, 443) and not parsed.username and not parsed.password
                and parsed.path == target.path and not parsed.query and not parsed.fragment)
    except ValueError:
        return False


def _image_signature(data):
    """比较原生上传的解码像素，允许 PNG 剪贴板重新编码，不接受缩图或换图。"""
    if not data or len(data) > 20 * 1024 * 1024:
        raise ValueError("图片数据大小异常")
    with Image.open(io.BytesIO(data)) as image:
        if image.format not in {"PNG", "JPEG"} or image.width * image.height > 40_000_000:
            raise ValueError("图片格式或尺寸异常")
        return image.size, hashlib.sha256(image.convert("RGBA").tobytes()).hexdigest()


def _decode_image(uri):
    if not isinstance(uri, str) or not re.fullmatch(r"data:image/(?:png|jpeg);base64,[A-Za-z0-9+/=]+", uri):
        raise ValueError("不是原生图片数据")
    data = base64.b64decode(uri.split(",", 1)[1], validate=True)
    _image_signature(data)
    return data


def _upload_file(request):
    """精确解析原生 multipart 单文件上传；查询接口或其他文件均不是证据。"""
    if request.method != "POST" or not _endpoint(request.url, UPLOAD_URL):
        return None
    content_type = request.headers.get("content-type", "")
    if not content_type.startswith("multipart/form-data;"):
        return None
    raw = request.post_data_buffer or b""
    if len(raw) > 21 * 1024 * 1024:
        return None
    message = BytesParser(policy=email_policy).parsebytes(
        b"Content-Type: " + content_type.encode("ascii") + b"\r\nMIME-Version: 1.0\r\n\r\n" + raw)
    parts = list(message.iter_parts())
    fields = {}
    for part in parts:
        name = part.get_param("name", header="content-disposition")
        if name in fields:
            return None
        fields[name] = part.get_payload(decode=True)
    if fields.get("type") != b"6" or fields.get("queryBase64") != b"true":
        return None
    return fields.get("file")


def _upload_filename(request):
    content_type = request.headers.get("content-type", "")
    message = BytesParser(policy=email_policy).parsebytes(
        b"Content-Type: " + content_type.encode("ascii") + b"\r\n\r\n" + (request.post_data_buffer or b""))
    files = [part.get_filename() for part in message.iter_parts()
             if part.get_param("name", header="content-disposition") == "file"]
    return files[0] if len(files) == 1 else None


def _native_text(content):
    class Reader(HTMLParser):
        def handle_data(self, data):
            self.parts.append(data)
    reader = Reader(convert_charrefs=True)
    reader.parts = []
    reader.feed(content or "")
    return "".join(reader.parts)


# CDP omits multipart file bytes. Observe only this exact native upload FormData;
# keep native request arguments, return values and synchronous exceptions intact.
_UPLOAD_OBSERVER = r"""(()=>{
    const queue=[], target='https://mp.yiche.com/api/upload_image/mp_real_upload';
    Object.defineProperty(window,'__postsailYicheUploadProofs',{value:queue,configurable:false});
    const observe=(method,url,body)=>{try{
        if(String(method).toUpperCase()!=='POST'||new URL(url,location.href).href!==target||!(body instanceof FormData))return;
        const files=body.getAll('file');if(files.length!==1||!(files[0] instanceof Blob)||
            body.getAll('type').length!==1||body.get('type')!=='6'||
            body.getAll('queryBase64').length!==1||body.get('queryBase64')!=='true')return;
        const file=files[0];if(file.size>20*1024*1024)return;
        queue.push({url:target,name:file.name,size:file.size,promise:new Promise(resolve=>{
            const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>resolve(null);reader.readAsDataURL(file);})});
    }catch{}};
    const requests=new WeakMap(),open=XMLHttpRequest.prototype.open,send=XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open=function(...args){const result=Reflect.apply(open,this,args);
        requests.set(this,{method:args[0],url:args[1]});return result;};
    XMLHttpRequest.prototype.send=function(...args){const r=requests.get(this);if(r)observe(r.method,r.url,args[0]);
        return Reflect.apply(send,this,args);};
    const fetch=window.fetch;window.fetch=function(...args){const input=args[0],init=args[1];
        if(init)observe(init.method||(input instanceof Request?input.method:'GET'),input instanceof Request?input.url:input,init.body);
        return Reflect.apply(fetch,this,args);};
})();"""


def _publish_body(request):
    if request.method != "POST" or not _endpoint(request.url, SAVE_URL):
        return None
    try:
        data = json.loads(request.post_data or "")
        body = data.get("param")
        return body if isinstance(body, dict) else None
    except (ValueError, AttributeError, TypeError):
        return None


def _receipt(body):
    """官方 status=1 还可能是每日上限或 result=false；只接受明确成功。"""
    if not isinstance(body, dict) or type(body.get("status")) is bool or body.get("status") not in (1, "1"):
        return None
    data = body.get("data")
    if (not isinstance(data, dict) or data.get("authMsgShow") not in (None, False, 0)
            or not (data.get("result") is True or type(data.get("result")) is int and data["result"] == 1)):
        return None
    identifier = data.get("newsId")
    if identifier is not None and (type(identifier) is bool or not re.fullmatch(r"[1-9][0-9]*", str(identifier))):
        return None
    return {"status": "submitted", "message": "易车号已明确接收本次文章，公开发表状态仍需核查",
            "platform_id": str(identifier) if identifier is not None else None,
            "platform_url": None, "platform_status": "已提交"}


_ARTICLE = """el=>{const vm=el.__vue__;
    if(!vm||vm.$options.name!=='Article'||vm.$el!==el||!vm.titleData||!vm.articleData)
        throw Error('易车原生 Article 组件不可读取');return vm;}"""

_STATE = """el=>{const vm=(""" + _ARTICLE + """)(el);return {
    title:vm.titleData.articleTitle,html:vm.content,newsId:vm.newsId,
    covers:vm.coverImages,coverKeys:vm.coverImagesKey,coverRadio:vm.coverRadio,
    upright:vm.uprightPic,reprint:vm.articleData.reprint,aiSummary:vm.articleData.aiSummary,
    declaration:vm.articleData.complianceType,source:vm.articleData.complianceRemark,
    schedule:vm.articleData.publishTime,white:vm.isVoteWhiteFlag,
    business:vm.hasNewsTask,topics:vm.newTopicList,hot:vm.hotCont,activities:vm.checkedList,
    program:vm.programId,category:vm.articleData.categoryId,
    serials:vm.page.carTagData,motos:vm.page.carTagMotoData};} """

_COVER_IMAGE_EDITOR = """el=>{const found=new Set();
    for(let node=el;node;node=node.parentElement){let vm=node.__vue__;
        for(let i=0;vm&&i<30;i++,vm=vm.$parent){const editor=vm.$refs&&vm.$refs.VueImageEditor;
            if(editor&&editor.$el&&el.contains(editor.$el)&&typeof editor.getImage==='function')found.add(editor);}}
    return found.size===1?[...found][0]:null;}"""

_COVER_PREVIEW_READY = """el=>{const editor=(""" + _COVER_IMAGE_EDITOR + """)(el);
    if(!editor||!editor.backgroundImg||!editor.backgroundImg.url)return false;
    const pending=[editor],seen=new Set(),ready=[];for(let i=0;pending.length&&i<200;i++){
        const vm=pending.pop();if(seen.has(vm))continue;seen.add(vm);pending.push(...(vm.$children||[]));
        const c=vm.canvas,b=c&&c.backgroundImage,info=vm.imgInfo;
        if(!info||!(info.width>0&&info.height>0)||!c||typeof c.getWidth!=='function'||
            typeof c.getHeight!=='function'||!(c.getWidth()>0&&c.getHeight()>0)||
            !b||typeof b.getElement!=='function')continue;
        const img=b.getElement();if(img&&img.complete&&img.naturalWidth>0&&img.src===editor.backgroundImg.url&&
            typeof c.getObjects==='function'&&c.getObjects().length===0)ready.push(vm);}
    return ready.length===1;}"""


class YicheArticleAdapter(NativeArticleAdapter):
    platform, label = "yiche", "易车号"
    editor_url = "https://mp.yiche.com/article/index-new"
    root_selector = ".article-main-new"
    title_selector = '.article-main-new .titles-form input[placeholder="请输入文章标题"]'
    editor_selector = '.article-main-new .article-container .ql-editor[contenteditable="true"]'
    publish_selector = '.article-main-new .article-footer button[data-ctitle="fabu"]'

    def __init__(self, snapshot, cover):
        super().__init__(snapshot, cover)
        self._uploads = {}
        self._pending_upload = None
        self._upload_requests = {}
        self._response_tasks = set()
        self._expected = None
        self._allowed_request = None
        self._receipt = None
        self._document = None

    def _validate_destination(self, page):
        if not _endpoint(page.url, self.editor_url):
            raise PreparationError("易车号未停留在空白原生文章入口，已阻止覆盖旧稿或误发")

    def _validate_inputs(self):
        if not 5 <= len(self.title) <= 28:
            raise PreparationError("易车号当前原生标题须为 5–28 字")
        known = {"vertical_cover_asset_id", "declaration", "source_url", "allow_forward", "allow_abstract"}
        if self.tags or any(key not in known for key in self.options):
            raise PreparationError("易车号尚不支持该原生选项或普通话题")
        for name in ("allow_forward", "allow_abstract"):
            if name in self.options and type(self.options[name]) is not bool:
                raise PreparationError("易车号转载和摘要授权必须为布尔值")
        declaration = self.options.get("declaration") or "内容无需标注"
        if declaration not in DECLARATIONS:
            raise PreparationError("易车号内容声明已更新，请重新选择原生声明")
        source = self.options.get("source_url") or ""
        if declaration == "内容为转载":
            if urlparse(source).scheme not in {"http", "https"} or not urlparse(source).hostname:
                raise PreparationError("易车号转载声明需要完整 HTTP/HTTPS 来源地址")
        elif source:
            raise PreparationError("易车号只有转载声明可填写来源地址")

    async def _state(self, page):
        root = await _unique(page.locator(self.root_selector), "易车号文章组件")
        try:
            return await root.evaluate(_STATE)
        except Exception as exc:
            raise PreparationError("易车号原生文章状态不可读取，请核对平台变化") from exc

    async def install_preparation_guard(self, page):
        if hasattr(self, "_guard"):
            return
        await page.add_init_script(_UPLOAD_OBSERVER)

        async def guard(route):
            request = route.request
            if _endpoint(request.url, SAVE_URL):
                data = _publish_body(request)
                if (self._submit_started and self.snapshot.get("mode") != "preview"
                        and self._allowed_request is None and self._matches_submission(data)):
                    self._allowed_request = request
                    return await route.fallback()
                return await route.abort()
            if _endpoint(request.url, UPLOAD_URL):
                try:
                    pending = self._pending_upload
                    uploaded = _upload_file(request)
                    proof = await page.evaluate("""async()=>{const queue=window.__postsailYicheUploadProofs;
                        if(!queue||queue.length!==1){if(queue)queue.length=0;return null;}
                        const item=queue.shift();return {url:item.url,name:item.name,size:item.size,uri:await item.promise};}""")
                    observed = _decode_image(proof["uri"]) if proof else None
                    if (pending and uploaded is not None and observed and proof["url"] == UPLOAD_URL
                            and proof["name"] == pending[2] == _upload_filename(request)
                            and proof["size"] == pending[3] == len(observed)
                            and _image_signature(observed) == pending[1]
                            and (not uploaded or _image_signature(uploaded) == pending[1])):
                        self._pending_upload = None
                        self._upload_requests[request] = pending[0]
                        return await route.fallback()
                except (ValueError, OSError, TypeError):
                    pass
                return await route.abort()
            parsed = urlparse(request.url)
            if request.method in {"GET", "HEAD", "OPTIONS"}:
                return await route.fallback()
            if (request.method == "POST" and parsed.scheme == "https" and parsed.netloc == "mp.yiche.com"
                    and parsed.path in READ_POST_PATHS and not parsed.query):
                return await route.fallback()
            await route.abort()

        async def capture(response):
            request = response.request
            try:
                if request is self._allowed_request and 200 <= response.status < 300:
                    self._receipt = _receipt(await response.json())
                kind = self._upload_requests.pop(request, None)
                if kind is None or not 200 <= response.status < 300:
                    return
                body = await response.json()
                if type(body.get("status")) is bool or body.get("status") not in (1, "1"):
                    return
                data = body.get("data")
                if not isinstance(data, dict):
                    return
                key, uri = data.get("imgKey"), data.get("imgBase64")
                if not isinstance(key, str) or not 1 <= len(key) <= 2048 or re.search(r'[\s<>"\x00-\x1f]', key):
                    return
                _decode_image(uri)
                if any(value["key"] == key for value in self._uploads.values()):
                    return
                self._uploads[kind] = {"key": key, "src": uri}
            except (ValueError, TypeError, OSError, AttributeError):
                return

        def listener(response):
            task = asyncio.create_task(capture(response))
            self._response_tasks.add(task)
            task.add_done_callback(self._response_tasks.discard)

        self._guard = guard
        await page.route("**/*", guard)
        page.on("response", listener)

    async def open_editor(self, page):
        self._validate_inputs()
        await self.install_preparation_guard(page)
        editor = await super().open_editor(page)
        self._validate_destination(page)
        try:
            await page.wait_for_function("""()=>{const login=window.Bitauto&&Bitauto.Login&&Bitauto.Login.result;
                return login&&login.isLogined===true&&typeof login.userId!=='boolean'&&/^[1-9][0-9]*$/.test(String(login.userId));}""",
                timeout=15000)
        except Exception as exc:
            raise PreparationError("易车号未取得官方登录脚本的正向身份结果，请重新登录") from exc
        state = await self._state(page)
        if (state.get("newsId") not in (0, "", None) or state.get("title") or
                normalize_text(_native_text(state.get("html"))) or (await _value(await self._title_field(page))).strip()
                or re.search(r"<(?:img|video|audio|table|iframe|object|embed|hr|canvas|svg)\b", state.get("html") or "", re.I)
                or normalize_text(await _value(editor)) or
                await editor.locator("img,video,audio,table,iframe,object,embed,hr,canvas,svg").count()):
            raise PreparationError("易车号编辑器已有标题或正文，请先保存原草稿；已阻止覆盖")
        if state.get("white") or state.get("business"):
            raise PreparationError("该易车账号出现白名单分类或商单流程，需人工核对专属必填项")
        return editor

    async def insert_body_images(self, page, editor, render_page, document):
        self._document = document
        for index, (marker, path) in enumerate(zip(document.markers, document.image_paths)):
            selected = await editor.evaluate("""(el,marker)=>{const walker=document.createTreeWalker(el,NodeFilter.SHOW_TEXT);
                let node;while(node=walker.nextNode()){const i=node.textContent.indexOf(marker);if(i<0)continue;
                el.focus();const range=document.createRange();range.setStart(node,i);range.setEnd(node,i+marker.length);
                const selection=getSelection();selection.removeAllRanges();selection.addRange(range);return true;}return false;}""", marker)
            if not selected:
                raise PreparationError("易车号正文图片定位标记丢失")
            kind = f"body:{index}"
            await _clipboard_image(page, render_page, Path(path))
            size = await page.evaluate("""async()=>{const items=await navigator.clipboard.read();
                if(items.length!==1)return null;return(await items[0].getType('image/png')).size;}""")
            self._pending_upload = (kind, _image_signature(Path(path).read_bytes()), "图片.png", size)
            await page.keyboard.press("ControlOrMeta+V")
            for _ in range(60):
                images = await self._body_images(editor)
                receipt = self._uploads.get(kind)
                if (receipt and len(images) == index + 1 and images[-1]["ready"]
                        and images[-1]["src"] == receipt["src"] and images[-1]["key"] == receipt["key"]):
                    if [image["src"] for image in images[:-1]] != document.uploaded_urls:
                        raise PreparationError("易车号改变了已上传正文图片的顺序")
                    document.uploaded_urls.append(receipt["src"])
                    break
                await page.wait_for_timeout(250)
            else:
                raise PreparationError("易车号正文图片未取得匹配本次文件的原生上传回执")

    async def _body_images(self, editor):
        return await editor.locator("img").evaluate_all("""images=>images.map(img=>({src:img.src,
            key:img.getAttribute('data-img-key'),ready:img.complete&&img.naturalWidth>0}))""")

    async def verify_uploaded_images(self, editor, images, document):
        native = await self._body_images(editor)
        if len(native) != len(document.image_paths):
            raise PreparationError("易车号原生正文图片数量不一致")
        for index, item in enumerate(native):
            receipt = self._uploads.get(f"body:{index}")
            if (not receipt or not item["ready"] or item["src"] != receipt["src"]
                    or item["key"] != receipt["key"] or images[index]["src"] != receipt["src"]):
                raise PreparationError("易车号正文图片缺少本次上传回执，不能把 Base64 预览视为上传成功")

    def _cover_file(self, vertical):
        path = self.option_assets.get("vertical_cover_asset_id") if vertical else self.cover
        if not path:
            raise PreparationError("易车号需要独立横版和竖版封面素材")
        path = Path(path)
        try:
            with Image.open(path) as image:
                width, height = image.size
                valid = image.format in {"PNG", "JPEG"}
            ratio = width / height
            valid = valid and width <= 5000 and path.stat().st_size <= 10 * 1024 * 1024
            valid = valid and (min(abs(ratio - .75), abs(ratio - 4 / 3)) <= .01 if vertical else width * 2 == height * 3)
        except (OSError, ValueError) as exc:
            raise PreparationError("易车号封面素材不可读取") from exc
        if not valid:
            raise PreparationError("易车号封面须为 JPEG/PNG、≤10MiB、宽≤5000px；横版3:2，竖版3:4或4:3；不自动裁剪")
        return path

    async def _cover_region(self, page, vertical):
        # 官方模板两区域均为 article-cover；标题的星号是前置必填标记。
        name = "竖版封面图" if vertical else "封面图"
        return await _unique(page.locator(self.root_selector + " .article-cover").filter(
            has=page.locator("label.item-title").filter(has_text=re.compile(r"^\s*\*?\s*" + name + r"\s*$"))),
            "易车号" + name)

    async def _full_crop(self, page, modal):
        # 官方 vue-cropper 公开 goAutoCrop/getImgAxis/getCropAxis，恢复完整图片范围。
        script = """async el=>{const roots=[el,...el.querySelectorAll('*')];const found=new Set();
            for(const node of roots){const vm=node.__vue__;if(vm&&typeof vm.goAutoCrop==='function'&&
                typeof vm.getImgAxis==='function'&&typeof vm.getCropAxis==='function')found.add(vm);}
            if(found.size!==1)return false;const cropper=[...found][0], axis=cropper.getImgAxis();
            if(!(axis.x2>axis.x1&&axis.y2>axis.y1)||cropper.rotate!==0)return false;
            cropper.goAutoCrop(axis.x2-axis.x1,axis.y2-axis.y1);await cropper.$nextTick();
            const crop=cropper.getCropAxis();return ['x1','x2','y1','y2'].every(k=>Math.abs(crop[k]-axis[k])<.75);} """
        for _ in range(40):
            if await modal.evaluate(script):
                return
            await page.wait_for_timeout(100)
        raise PreparationError("易车号封面裁剪框未覆盖完整原图，请提供精确比例素材；已阻止自动裁剪")

    async def _upload_cover(self, page, vertical):
        path = self._cover_file(vertical)
        kind = "vertical" if vertical else "horizontal"
        region = await self._cover_region(page, vertical)
        # 更换字段位于 cover-mask；仅主上传组件的 input 能接收初次上传。
        upload = await _unique(region.locator('.upload-image > .avatar-uploader input[type="file"]'),
                               "易车号封面上传字段", visible=False, enabled=True)
        if not vertical:
            self._pending_upload = (kind, _image_signature(path.read_bytes()), path.name, path.stat().st_size)
        await upload.set_input_files(str(path))
        if vertical:
            await page.get_by_role("dialog", name="封面编辑", exact=True).wait_for(state="visible", timeout=15000)
            modal = await _unique(page.get_by_role("dialog", name="封面编辑", exact=True), "易车号封面编辑窗口")
            await self._full_crop(page, modal)
            await (await _unique(modal.get_by_role("button", name="完成裁剪", exact=True), "易车号完成裁剪", enabled=True)).click()
            # getImage 在背景未加载时会把原生画布改为空尺寸，不能以调用它来轮询。
            # 先只读确认真实 Home/Fabric 背景已完成加载且没有额外模板，再读取一次。
            for _ in range(40):
                if await modal.evaluate(_COVER_PREVIEW_READY):
                    break
                await page.wait_for_timeout(100)
            else:
                raise PreparationError("易车号封面最终预览尚未准备好")
            uri = await modal.evaluate("el=>(" + _COVER_IMAGE_EDITOR + ")(el).getImage()")
            try:
                data = _decode_image(uri)
            except ValueError as exc:
                raise PreparationError("易车号封面最终预览为空或未完成加载") from exc
            self._pending_upload = (kind, _image_signature(data), path.name, len(data))
            await (await _unique(modal.get_by_role("button", name="确定", exact=True), "易车号封面确认", enabled=True)).click()
        for _ in range(60):
            state, receipt = await self._state(page), self._uploads.get(kind)
            src = state.get("upright", {}).get("url") if vertical else state.get("covers", [None])[0]
            key = state.get("upright", {}).get("imgKey") if vertical else state.get("coverKeys", [None])[0]
            if receipt and src == receipt["src"] and key == receipt["key"]:
                try:
                    await self._verify_cover_dom(region, receipt)
                    return
                except PreparationError:
                    # 原生响应已经写入组件，较大的 Base64 预览仍可能正在解码。
                    pass
            await page.wait_for_timeout(250)
        raise PreparationError("易车号封面未取得与本次文件匹配的原生上传回执")

    async def _verify_cover_dom(self, region, receipt):
        images = await region.locator(".avatar-uploader img.avatar").evaluate_all(
            "images=>images.map(img=>({src:img.src,ready:img.complete&&img.naturalWidth>0}))")
        if images != [{"src": receipt["src"], "ready": True}]:
            raise PreparationError("易车号封面可见预览与原生上传回执不一致")

    async def _radio(self, page, label, value):
        row = await _unique(page.locator(self.root_selector + " .item-box").filter(
            has=page.locator("label.item-title").filter(has_text=re.compile(r"^\s*" + label + r"\s*\??\s*$"))),
            "易车号" + label)
        field = await _unique(row.get_by_role("radio", name=value, exact=True), "易车号" + label + value, enabled=True)
        await field.check()
        if not await field.is_checked():
            raise PreparationError("易车号原生选项未选中")

    async def apply_options(self, page, editor):
        self._validate_inputs()
        self._validate_destination(page)
        self._cover_file(False)
        self._cover_file(True)
        await self._radio(page, "同意转发", "是" if self.options.get("allow_forward", False) else "否")
        await self._radio(page, "同意生成摘要", "是" if self.options.get("allow_abstract", False) else "否")
        declaration = self.options.get("declaration") or "内容无需标注"
        field = await _unique(page.locator(self.root_selector + " .content-statement-box").get_by_role(
            "radio", name=declaration, exact=True), "易车号内容声明", enabled=True)
        await field.check()
        if declaration == "内容为转载":
            source = await _unique(page.locator('.content-statement-source-input input'), "易车号转载来源", enabled=True)
            await source.fill(self.options["source_url"])
        horizontal = await self._cover_region(page, False)
        await (await _unique(horizontal.get_by_role("radio", name="单图", exact=True), "易车号单图封面", enabled=True)).check()
        await self._upload_cover(page, False)
        await self._upload_cover(page, True)

    async def verify_options(self, page, editor):
        state = await self._state(page)
        if state.get("white") or state.get("business"):
            raise PreparationError("易车号当前账号出现专属分类或商单必填流程，请人工核对")
        for name, expected in (("reprint", int(self.options.get("allow_forward", False))),
                               ("aiSummary", int(self.options.get("allow_abstract", False))),
                               ("declaration", DECLARATIONS[self.options.get("declaration") or "内容无需标注"])):
            if type(state.get(name)) is not int or state[name] != expected:
                raise PreparationError("易车号原生声明或授权读回不一致")
        if (state.get("source") or "") != (self.options.get("source_url") or ""):
            raise PreparationError("易车号转载来源读回不一致")
        if state.get("coverRadio") != 0 or state.get("schedule") or state.get("newsId") not in (0, "", None):
            raise PreparationError("易车号出现旧稿、定时或三图封面设置")
        if any(state.get(key) for key in ("topics", "hot", "activities", "program", "category", "serials", "motos")):
            raise PreparationError("易车号出现未经请求的话题、分类、关联车型或活动，请先清理平台默认项")
        for vertical in (False, True):
            kind = "vertical" if vertical else "horizontal"
            receipt = self._uploads.get(kind)
            src = state["upright"]["url"] if vertical else state["covers"][0]
            key = state["upright"]["imgKey"] if vertical else state["coverKeys"][0]
            if not receipt or src != receipt["src"] or key != receipt["key"]:
                raise PreparationError("易车号双封面状态与本次上传回执不一致")
            await self._verify_cover_dom(await self._cover_region(page, vertical), receipt)
            if vertical:
                dimensions, _ = _image_signature(_decode_image(receipt["src"]))
                upright = state["upright"]
                if (type(upright.get("width")) is not int or type(upright.get("height")) is not int
                        or (upright["width"], upright["height"]) != dimensions
                        or type(upright.get("sourceType")) is not int or upright["sourceType"] != 1):
                    raise PreparationError("易车号竖封面尺寸或来源与本次上传图不一致")

    async def verify_body(self, page, editor, document):
        state = await self._state(page)
        self._document = document
        if normalize_text(_native_text(state["html"])) != normalize_text(document.expected_text):
            raise PreparationError("易车号待提交正文与本次完整原稿不一致")
        # 离线副本验证 Vue 表单正文，不能只验证可见 Quill DOM。
        check = await page.context.new_page()
        try:
            await check.route("**/*", lambda route: route.abort())
            await check.set_content('<main id="content"></main>')
            body = check.locator("#content")
            await body.evaluate("(el,html)=>el.innerHTML=html", state["html"])
            await body.evaluate("el=>Promise.all([...el.querySelectorAll('img')].map(img=>img.decode()))")
            await verify_rich_structure(body, document.paste_html)
            if normalize_text(await body_sequence(body)) != normalize_text(inspect_text(document.paste_html)):
                raise PreparationError("易车号表单正文图片与相邻段落位置发生变化")
            await self.verify_uploaded_images(body, await self._body_images(body), document)
            # 按官方 commandParams/handlerImgKeys 的规则生成纯数据副本，未调用保存或发布。
            serialized = await body.evaluate(r"""(el,original)=>{let content=original.replace(/class="ql-align-center"/gi,
                'class="ql-align-center" style="text-align:center"');for(const name of ['data-extendid','data-extendtype']){
                let n=0;content=content.replace(new RegExp(name,'g'),()=>++n===2?name:(name==='data-extendid'?'extendIdInvalid':'extendTypeInvalid'));}
                return content.replace(/<img[^<>]+>/gi,html=>{const temp=document.createElement('p');temp.innerHTML=html;
                    const img=temp.firstElementChild,key=img.getAttribute('data-img-key');
                    if(!key||key==='null')throw Error('缺少本次上传素材键');img.removeAttribute('data-img-key');
                    img.setAttribute('src',key);img.className='imgborder';return temp.innerHTML;});} """, state["html"])
        finally:
            await check.close()
        upright = state["upright"]
        self._expected = {
            "title": self.title, "content": serialized, "cover": [self._uploads["horizontal"]["key"]],
            "uprightPic": {"url": self._uploads["vertical"]["key"], "width": upright["width"],
                           "height": upright["height"], "sourceType": upright["sourceType"]},
            "imgKeys": ",".join([self._uploads[f"body:{i}"]["key"] for i in range(len(document.image_paths))]
                                + [self._uploads["vertical"]["key"], self._uploads["horizontal"]["key"]]),
            "reprint": int(self.options.get("allow_forward", False)),
            "aiSummary": int(self.options.get("allow_abstract", False)),
            "complianceType": DECLARATIONS[self.options.get("declaration") or "内容无需标注"],
            "complianceRemark": self.options.get("source_url") or "",
        }

    def _matches_submission(self, body):
        if not isinstance(body, dict) or not self._expected:
            return False
        if any(type(body.get(name)) is not int or body[name] != value for name, value in
               (("action", 2), ("publishType", 2), ("newsId", 0), ("reprint", self._expected["reprint"]),
                ("aiSummary", self._expected["aiSummary"]), ("complianceType", self._expected["complianceType"]))):
            return False
        if any(body.get(name) != value for name, value in self._expected.items()):
            return False
        if any(body.get(name) for name in ("publishTime", "hotTopicIds", "relatedActivityIds", "relatedSerialId",
                                           "relateMotorcycleIds", "categoryId", "voteId", "programId", "relatedTagId", "keywords")):
            return False
        return body.get("businessTaskInfo") in (None, {}, {"taskNum": -1})

    async def submit(self, page, on_submit):
        if self._submit_started:
            raise PreparationError("本任务已尝试提交，请先核对易车号记录")
        self._validate_destination(page)
        if not self._expected or not self._document:
            raise PreparationError("易车号尚未完成正文与双封面核验")
        editor = await _unique(page.locator(self.editor_selector), "易车号文章正文")
        await self.verify_title(page)
        await self.verify_options(page, editor)
        from utils.articles.adapter import _verify_final_body
        await _verify_final_body(editor, self._document, self.platform, [], image_verifier=self.verify_uploaded_images)
        await self.verify_body(page, editor, self._document)
        button = await _unique(page.locator(self.publish_selector), "易车号原生提交按钮", enabled=True)
        if (await button.inner_text()).strip() != "提交":
            raise PreparationError("易车号提交按钮文字发生变化")
        await button.scroll_into_view_if_needed()
        await self._mark_submit(on_submit)
        await button.click(timeout=10000)

    async def read_result(self, page):
        if self._response_tasks:
            await asyncio.gather(*tuple(self._response_tasks), return_exceptions=True)
        return self._receipt or {"status": "unknown", "message": "易车号尚未返回本次文章的明确接收回执，请核查平台记录",
                                 "platform_id": None, "platform_url": None, "platform_status": "待确认"}
