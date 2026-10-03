"""易车号原生协议、双封面及单次提交边界；受控页面不是线上验收。"""
import base64
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from PIL import Image

from utils.articles.browser import PreparationError, PreparedDocument, launch_article_browser
from utils.articles.yiche import (
    DECLARATIONS, SAVE_URL, UPLOAD_URL, YicheArticleAdapter,
    _decode_image, _image_signature, _publish_body, _receipt, _upload_file,
)


TITLE = "易车号原生文章测试"


def png(width=600, height=400, color="red"):
    stream = io.BytesIO()
    Image.new("RGB", (width, height), color).save(stream, "PNG")
    return stream.getvalue()


def multipart(data, *, kind="6"):
    body = b""
    for name, value in (("type", kind.encode()), ("queryBase64", b"true"), ("file", data)):
        filename = '; filename="image.png"' if name == "file" else ""
        body += (f'--boundary\r\nContent-Disposition: form-data; name="{name}"{filename}\r\n\r\n'.encode()
                 + value + b"\r\n")
    return SimpleNamespace(url=UPLOAD_URL, method="POST", post_data_buffer=body + b"--boundary--\r\n",
                           headers={"content-type": "multipart/form-data; boundary=boundary"})


class YicheProtocolTests(unittest.TestCase):
    def test_requires_native_param_envelope_and_precise_endpoint(self):
        request = SimpleNamespace(url=SAVE_URL, method="POST", post_data=json.dumps({"param": {"action": 2}}))
        self.assertEqual(_publish_body(request), {"action": 2})
        for url in (SAVE_URL + "?action=2", SAVE_URL.replace("mp.yiche.com", "evil.test"), SAVE_URL + "/"):
            request.url = url
            self.assertIsNone(_publish_body(request))
        request.url, request.post_data = SAVE_URL, '{"action":2}'
        self.assertIsNone(_publish_body(request))

    def test_status_one_is_not_enough_for_a_receipt(self):
        for data in ({"result": True}, {"result": 1, "newsId": "123"}):
            self.assertEqual(_receipt({"status": "1", "data": data})["status"], "submitted")
        for data in ({}, {"result": False}, {"result": "1"}, {"result": 0},
                     {"result": True, "authMsgShow": True}, {"result": True, "newsId": False},
                     {"result": True, "newsId": "draft-1"}):
            with self.subTest(data=data):
                self.assertIsNone(_receipt({"status": 1, "data": data}))
        self.assertIsNone(_receipt({"status": True, "data": {"result": True}}))

    def test_multipart_is_bound_to_one_native_image_file(self):
        image = png()
        self.assertEqual(_upload_file(multipart(image)), image)
        self.assertIsNone(_upload_file(multipart(image, kind="2")))
        request = multipart(image)
        request.post_data_buffer += b"garbage"
        request.url = UPLOAD_URL + "?other=true"
        self.assertIsNone(_upload_file(request))

    def test_image_evidence_rejects_svg_and_changed_pixels(self):
        data = png()
        uri = "data:image/png;base64," + base64.b64encode(data).decode()
        self.assertEqual(_decode_image(uri), data)
        self.assertNotEqual(_image_signature(data), _image_signature(png(color="blue")))
        with self.assertRaises(ValueError):
            _decode_image("data:image/svg+xml;base64,PHN2Zz4=")

    def test_native_declarations_are_not_guessed_from_old_contract(self):
        for declaration in DECLARATIONS:
            options = {"declaration": declaration}
            if declaration == "内容为转载":
                options["source_url"] = "https://example.com/source"
            YicheArticleAdapter({"title": TITLE, "options": options}, None)._validate_inputs()
        for options in ({"declaration": "AI生成"}, {"declaration": "内容为转载"},
                        {"declaration": "内容无需标注", "source_url": "https://example.com"},
                        {"allow_forward": 1}):
            with self.subTest(options=options), self.assertRaises(PreparationError):
                YicheArticleAdapter({"title": TITLE, "options": options}, None)._validate_inputs()

    def test_cover_ratio_must_not_silently_crop_original(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cover.png"
            path.write_bytes(png(600, 400))
            adapter = YicheArticleAdapter({"title": TITLE}, path)
            self.assertEqual(adapter._cover_file(False), path)
            path.write_bytes(png(600, 450))
            with self.assertRaises(PreparationError):
                adapter._cover_file(False)
            adapter.option_assets["vertical_cover_asset_id"] = path
            self.assertEqual(adapter._cover_file(True), path)


FIXTURE = r'''<!doctype html><html><body>
<div class="article-main-new">
 <form class="titles-form"><input placeholder="请输入文章标题" oninput="vm.titleData.articleTitle=this.value"></form>
 <section class="article-container"><div class="ql-editor" contenteditable="true" style="min-height:120px"></div></section>
 <div class="article-cover item-box" id="horizontal"><label class="item-title"><i>*</i>封面图</label>
   <label><input type="radio" name="cover" checked onchange="vm.coverRadio=0">单图</label>
   <label><input type="radio" name="cover" onchange="vm.coverRadio=1">三图</label>
   <div class="upload-image"><div class="avatar-uploader"><input type="file" onchange="uploadHorizontal(this.files[0])"></div></div></div>
 <div class="article-cover item-box" id="vertical"><label class="item-title"><i>*</i>竖版封面图</label>
   <div class="upload-image"><div class="avatar-uploader"><input type="file" onchange="openCrop(this.files[0])"></div></div></div>
 <div class="item-box"><label class="item-title">同意转发 ?</label>
   <label><input type="radio" name="forward" checked onchange="vm.articleData.reprint=1">是</label>
   <label><input type="radio" name="forward" onchange="vm.articleData.reprint=0">否</label></div>
 <div class="item-box"><label class="item-title">同意生成摘要 ?</label>
   <label><input type="radio" name="abstract" checked onchange="vm.articleData.aiSummary=1">是</label>
   <label><input type="radio" name="abstract" onchange="vm.articleData.aiSummary=0">否</label></div>
 <div class="content-statement-box item-box"><label class="item-title">添加内容声明</label>
  <label><input type="radio" name="declaration" onchange="vm.articleData.complianceType=0">内容无需标注</label>
  <label><input type="radio" name="declaration" onchange="vm.articleData.complianceType=1">含AI生成内容</label>
  <label><input type="radio" name="declaration" onchange="vm.articleData.complianceType=4;document.querySelector('.content-statement-source-input').hidden=false">内容为转载</label>
  <div class="content-statement-source-input" hidden><input oninput="vm.articleData.complianceRemark=this.value"></div></div>
 <div class="article-footer"><button type="button" data-ctitle="fabu" onclick="submitArticle()">提交</button></div>
</div>
<script>
const root=document.querySelector('.article-main-new'),body=document.querySelector('.ql-editor');
window.Bitauto={Login:{result:{isLogined:true,userId:123}}};
window.vm=root.__vue__={$options:{name:'Article'},$el:root,titleData:{articleTitle:''},content:'',newsId:0,
coverImages:['','',''],coverImagesKey:['','',''],coverRadio:0,uprightPic:{url:'',imgKey:'',width:0,height:0,sourceType:1},
articleData:{reprint:1,aiSummary:1,complianceType:'',complianceRemark:'',publishTime:'',categoryId:''},
isVoteWhiteFlag:false,hasNewsTask:false,newTopicList:[],hotCont:[],checkedList:[],programId:'',page:{carTagData:[],carTagMotoData:[]}};
function setBody(html){body.innerHTML=html;vm.content=html;}
async function fileURI(file){return await new Promise(resolve=>{const r=new FileReader();r.onload=()=>resolve(r.result);r.readAsDataURL(file);});}
async function upload(file){const form=new FormData();form.append('type','6');form.append('queryBase64','true');form.append('file',file);
 return await (await fetch('/api/upload_image/mp_real_upload',{method:'POST',body:form})).json();}
function coverImg(kind,data){const parent=document.querySelector('#'+kind+' .avatar-uploader');
 parent.querySelectorAll('img').forEach(i=>i.remove());const img=new Image();img.className='avatar';img.src=data.imgBase64;parent.appendChild(img);}
async function uploadHorizontal(file){const res=await upload(file);vm.coverImages[0]=res.data.imgBase64;
 vm.coverImagesKey[0]=res.data.imgKey;coverImg('horizontal',res.data);}
async function openCrop(file){const uri=await fileURI(file),img=new Image();img.src=uri;await img.decode();
 const modal=document.createElement('div');modal.setAttribute('role','dialog');modal.setAttribute('aria-label','封面编辑');
 modal.innerHTML='<div class="crop"></div><button type="button">完成裁剪</button>';document.body.appendChild(modal);
 const crop=modal.querySelector('.crop');let axis={x1:0,x2:img.width,y1:0,y2:img.height},current={x1:10,x2:100,y1:10,y2:100};
 crop.__vue__={rotate:0,getImgAxis:()=>axis,getCropAxis:()=>current,goAutoCrop:(w,h)=>{if(!window.badCrop)current={x1:0,x2:w,y1:0,y2:h};},$nextTick:async()=>{}};
 const imageEditor={$el:modal,backgroundImg:{url:uri},getImage:()=>{window.imageReads=(window.imageReads||0)+1;return uri;},
 $children:[{imgInfo:{width:img.width,height:img.height},canvas:{backgroundImage:{getElement:()=>img},
 getWidth:()=>window.previewNotReady?0:img.width,getHeight:()=>img.height,getObjects:()=>[]}}]};
 modal.__vue__={$refs:{VueImageEditor:imageEditor}};
 modal.querySelector('button').onclick=()=>{modal.innerHTML='<button type="button">确定</button>';modal.querySelector('button').onclick=async()=>{
   const res=await upload(file);vm.uprightPic={url:res.data.imgBase64,imgKey:res.data.imgKey,width:img.width,height:img.height,sourceType:1};
   coverImg('vertical',res.data);modal.remove();};};}
body.addEventListener('paste',async event=>{const file=[...event.clipboardData.files][0];if(!file)return;event.preventDefault();
 const selection=getSelection(),range=selection.getRangeAt(0);range.deleteContents();const node=new Image();
 node.src=await fileURI(file);range.insertNode(node);const res=await upload(new File([file],'图片.png',{type:'image/png'}));node.src=res.data.imgBase64;node.setAttribute('data-img-key',res.data.imgKey);vm.content=body.innerHTML;
 if(!vm.coverImages[0]){vm.coverImages[0]=res.data.imgBase64;vm.coverImagesKey[0]=res.data.imgKey;
 document.querySelector('#horizontal .avatar-uploader').classList.add('cover-img');coverImg('horizontal',res.data);}});
function nativePayload(){let content=vm.content.replace(/<img[^<>]+>/gi,html=>{const el=document.createElement('p');el.innerHTML=html;
 const img=el.firstElementChild,key=img.getAttribute('data-img-key');img.removeAttribute('data-img-key');img.setAttribute('src',key);img.className='imgborder';return el.innerHTML;});
 return {title:vm.titleData.articleTitle,content,newsId:0,action:2,publishType:2,publishTime:'',cover:[vm.coverImagesKey[0]],
 uprightPic:{url:vm.uprightPic.imgKey,width:vm.uprightPic.width,height:vm.uprightPic.height,sourceType:1},
 imgKeys:[...[...body.querySelectorAll('img')].map(i=>i.getAttribute('data-img-key')),vm.uprightPic.imgKey,vm.coverImagesKey[0]].join(','),
 reprint:vm.articleData.reprint,aiSummary:vm.articleData.aiSummary,complianceType:vm.articleData.complianceType,
 complianceRemark:vm.articleData.complianceRemark,businessTaskInfo:null};}
async function submitArticle(){window.clicks=(window.clicks||0)+1;const payload=nativePayload();Object.assign(payload,window.tamper||{});
 try{await fetch('/web_mp/api/v1/pub/savenews',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({param:payload})});}catch{}}
</script></body></html>'''


@unittest.skipUnless(os.environ.get("OMNIPOST_BROWSER_TESTS") == "1", "受控浏览器用例需显式启用")
class YicheBrowserTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from playwright.async_api import async_playwright
        import conf
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.horizontal, self.vertical, self.body_image = (self.directory / name for name in ("h.png", "v.png", "b.png"))
        self.horizontal.write_bytes(png())
        self.vertical.write_bytes(png(300, 400, "blue"))
        self.body_image.write_bytes(png(480, 320, "green"))
        self.runtime = await async_playwright().start()
        self.browser = await launch_article_browser(self.runtime, True, getattr(conf, "LOCAL_CHROME_PATH", ""))
        self.context = await self.browser.new_context(service_workers="block", permissions=["clipboard-read", "clipboard-write"])
        self.page = await self.context.new_page()
        self.network = []
        self.response = {"status": "1", "data": {"result": True, "newsId": 123}}
        self.response_delay = 0

        async def route_handler(route):
            request = route.request
            if request.method == "POST":
                self.network.append(request.url)
                if request.url == UPLOAD_URL:
                    data = _upload_file(request)
                    # Chromium CDP omits file bytes; the test server knows the fixture files.
                    if data == b"":
                        from utils.articles.yiche import _upload_filename
                        name = _upload_filename(request)
                        data = {"h.png": self.horizontal, "v.png": self.vertical,
                                "图片.png": self.body_image}[name].read_bytes()
                    await route.fulfill(content_type="application/json", body=json.dumps({"status": "1", "data": {
                        "imgKey": f"key-{len(self.network)}", "imgBase64": "data:image/png;base64," + base64.b64encode(data).decode()}}))
                else:
                    if self.response_delay:
                        import asyncio
                        await asyncio.sleep(self.response_delay)
                    await route.fulfill(content_type="application/json", body=json.dumps(self.response))
            else:
                await route.fulfill(content_type="text/html; charset=utf-8", body=FIXTURE)
        await self.context.route("**/*", route_handler)

    async def asyncTearDown(self):
        await self.context.close()
        await self.browser.close()
        await self.runtime.stop()
        self.temp.cleanup()

    def adapter(self, mode="publish", options=None):
        adapter = YicheArticleAdapter({"title": TITLE, "mode": mode, "options": options or {}}, self.horizontal)
        adapter.option_assets["vertical_cover_asset_id"] = self.vertical
        return adapter

    async def prepare(self, adapter, image=False):
        editor = await adapter.open_editor(self.page)
        await adapter.fill_title(self.page)
        html = '<p>前文</p><p>OMNIPOSTIMAGE0000END</p><p>后文</p>' if image else '<p><strong>完整正文</strong></p>'
        text = "前文后文" if image else "完整正文"
        await self.page.evaluate("setBody", html)
        document = PreparedDocument(html, html, text, [self.body_image] if image else [],
                                    ["OMNIPOSTIMAGE0000END"] if image else [], [])
        render = await self.context.new_page()
        await adapter.insert_body_images(self.page, editor, render, document)
        await render.close()
        await adapter.apply_options(self.page, editor)
        await adapter.verify_options(self.page, editor)
        await adapter.verify_body(self.page, editor, document)
        return editor, document

    async def post(self, url=SAVE_URL, data=None):
        return await self.page.evaluate("""async ({url,data})=>{try{return(await fetch(url,{method:'POST',
            headers:{'Content-Type':'application/json'},body:JSON.stringify({param:data})})).ok}catch{return false;}}""",
            {"url": url, "data": data or {"action": 2}})

    async def test_preview_blocks_save_publish_and_unknown_writes_before_navigation(self):
        adapter = self.adapter("preview")
        await adapter.install_preparation_guard(self.page)
        await self.page.goto(adapter.editor_url)
        self.assertFalse(await self.post())
        self.assertFalse(await self.post(data={"action": 0}))
        self.assertFalse(await self.post("https://mp.yiche.com/unknown-save"))
        self.assertEqual(self.network, [])

    async def test_upload_requires_fresh_native_file_proof_and_exact_pixels(self):
        adapter = self.adapter()
        await adapter.open_editor(self.page)
        # A direct fetch with a forged multipart body has no native FormData proof.
        adapter._pending_upload = ("horizontal", _image_signature(self.horizontal.read_bytes()), "h.png", self.horizontal.stat().st_size)
        sent = await self.page.evaluate("""async()=>{try{return(await fetch('/api/upload_image/mp_real_upload',
            {method:'POST',body:'file=unobserved'})).ok}catch{return false;}}""")
        self.assertFalse(sent)
        self.assertEqual(self.network, [])
        # A genuine FormData upload of another file must still be blocked.
        file = self.page.locator('#horizontal input[type="file"]')
        await file.set_input_files(str(self.vertical))
        await self.page.wait_for_timeout(200)
        self.assertEqual(self.network, [])
        self.assertEqual(adapter._uploads, {})
        wrong = png(color="blue")
        adapter._pending_upload = ("horizontal", _image_signature(self.horizontal.read_bytes()), "h.png", len(wrong))
        await file.set_input_files({"name": "h.png", "mimeType": "image/png", "buffer": wrong})
        await self.page.wait_for_timeout(200)
        self.assertEqual(self.network, [])

    async def test_upload_proof_is_consumed_once(self):
        adapter = self.adapter()
        await adapter.open_editor(self.page)
        await adapter._upload_cover(self.page, False)
        count = len(self.network)
        await self.page.evaluate("uploadHorizontal(document.querySelector('#horizontal input[type=file]').files[0]).catch(()=>{})")
        self.assertEqual(len(self.network), count)

    async def test_existing_title_or_media_is_not_overwritten(self):
        adapter = self.adapter()
        await self.page.goto(adapter.editor_url)
        for content in ("vm.titleData.articleTitle='旧稿'", "setBody('<hr>')", "vm.content='<hr>'"):
            await self.page.evaluate(content)
            original_goto = self.page.goto
            self.page.goto = AsyncMock()
            try:
                with self.assertRaisesRegex(PreparationError, "已有标题或正文"):
                    await adapter.open_editor(self.page)
            finally:
                self.page.goto = original_goto
            await self.page.evaluate("vm.titleData.articleTitle='';setBody('')")

    async def test_native_dual_cover_and_authorization_defaults_read_back(self):
        adapter = self.adapter()
        await self.prepare(adapter)
        self.assertEqual(set(adapter._uploads), {"horizontal", "vertical"})
        self.assertEqual(await self.page.evaluate("[vm.articleData.reprint,vm.articleData.aiSummary]"), [0, 0])
        self.assertEqual(self.network, [UPLOAD_URL, UPLOAD_URL])

    async def test_body_image_requires_upload_receipt_and_native_key(self):
        adapter = self.adapter()
        editor, document = await self.prepare(adapter, image=True)
        self.assertEqual(len(document.uploaded_urls), 1)
        images = await adapter._body_images(editor)
        await adapter.verify_uploaded_images(editor, images, document)
        await editor.locator("img").evaluate("img=>img.setAttribute('data-img-key','unrelated')")
        with self.assertRaisesRegex(PreparationError, "上传回执"):
            await adapter.verify_uploaded_images(editor, images, document)

    async def test_serialized_form_must_preserve_image_position(self):
        adapter = self.adapter()
        editor, document = await self.prepare(adapter, image=True)
        await self.page.evaluate("const el=document.createElement('div');el.innerHTML=vm.content;el.appendChild(el.querySelector('img'));vm.content=el.innerHTML")
        with self.assertRaisesRegex(PreparationError, "相邻段落"):
            await adapter.verify_body(self.page, editor, document)

    async def test_one_exact_native_submit_is_the_only_allowed_request(self):
        adapter = self.adapter()
        await self.prepare(adapter, image=True)
        marks = []
        async with self.page.expect_response(lambda response: response.url == SAVE_URL):
            await adapter.submit(self.page, lambda: marks.append(True))
        self.assertEqual(marks, [True])
        self.assertEqual((await adapter.read_result(self.page))["status"], "submitted")
        self.assertEqual(self.network.count(SAVE_URL), 1)
        await self.page.evaluate("submitArticle()")
        self.assertEqual(self.network.count(SAVE_URL), 1)
        with self.assertRaises(PreparationError):
            await adapter.submit(self.page, lambda: marks.append(True))

    async def test_delayed_receipt_remains_pollable_unknown(self):
        adapter = self.adapter()
        await self.prepare(adapter)
        self.response_delay = .4
        await adapter.submit(self.page, lambda: None)
        self.assertEqual((await adapter.read_result(self.page))["status"], "unknown")
        await self.page.wait_for_timeout(600)
        self.assertEqual((await adapter.read_result(self.page))["status"], "submitted")

    async def test_draft_wrong_cover_or_authorization_is_not_the_expected_submission(self):
        adapter = self.adapter()
        await self.prepare(adapter)
        body = await self.page.evaluate("nativePayload()")
        self.assertTrue(adapter._matches_submission(body))
        for changes in ({"action": 0}, {"newsId": 999}, {"publishType": 1}, {"reprint": True},
                        {"cover": ["other-key"]}, {"imgKeys": "different-order"},
                        {"aiSummary": 1}, {"complianceType": 1}, {"publishTime": "2026-10-04"}):
            with self.subTest(changes=changes):
                self.assertFalse(adapter._matches_submission(body | changes))

    async def test_same_title_wrong_payload_is_blocked_after_submit_boundary(self):
        adapter = self.adapter()
        await self.prepare(adapter)
        await self.page.evaluate("window.tamper={content:'另一篇正文'}")
        await adapter.submit(self.page, lambda: None)
        self.assertTrue(adapter._submit_started)
        self.assertEqual((await adapter.read_result(self.page))["status"], "unknown")
        self.assertNotIn(SAVE_URL, self.network)

    async def test_persistence_failure_prevents_click(self):
        adapter = self.adapter()
        await self.prepare(adapter)
        def failed():
            raise RuntimeError("database unavailable")
        with self.assertRaises(RuntimeError):
            await adapter.submit(self.page, failed)
        self.assertFalse(adapter._submit_started)
        self.assertFalse(await self.page.evaluate("Boolean(window.clicks)"))

    async def test_crop_must_cover_whole_image(self):
        adapter = self.adapter()
        await adapter.open_editor(self.page)
        await self.page.evaluate("window.badCrop=true")
        with self.assertRaisesRegex(PreparationError, "完整原图"):
            await adapter._upload_cover(self.page, True)
        self.assertNotIn(UPLOAD_URL, self.network)

    async def test_cover_preview_wait_does_not_call_destructive_get_image_early(self):
        adapter = self.adapter()
        await adapter.open_editor(self.page)
        await self.page.evaluate("window.previewNotReady=true;setTimeout(()=>window.previewNotReady=false,500)")
        await adapter._upload_cover(self.page, True)
        self.assertEqual(await self.page.evaluate("window.imageReads"), 1)

    async def test_reprint_requires_native_source_field_and_readback(self):
        adapter = self.adapter(options={"declaration": "内容为转载", "source_url": "https://example.com/source",
                                        "allow_forward": True, "allow_abstract": True})
        await self.prepare(adapter)
        self.assertEqual(adapter._expected["complianceType"], 4)
        self.assertEqual(adapter._expected["complianceRemark"], "https://example.com/source")
        self.assertEqual(adapter._expected["reprint"], 1)
